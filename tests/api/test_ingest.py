"""Tests for admin ingest API."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config
from ee_wiki.api.ingest_jobs import reset_ingest_job_manager
from ee_wiki.ingestion.cleanup import RemovedProcessed
from ee_wiki.ingestion.pipeline import IngestionError, IngestResult, IngestRunResult
from ee_wiki.knowledge.indexer.build import IndexBuildResult
from ee_wiki.knowledge.indexer.store import IndexManifest
from ee_wiki.knowledge.store.processed import ProcessedPaths


@pytest.fixture(autouse=True)
def _reset_ingest_jobs() -> None:
    """Isolate in-memory job state across tests."""
    reset_ingest_job_manager()
    yield
    reset_ingest_job_manager()


def _mock_config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.raw_dir = tmp_path / "data" / "raw"
    config.repo_root = tmp_path
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    config.api.public_base_url = None
    config.api.max_concurrent_ingest_jobs = 1
    config.api.ingest_api_key = None
    return config


def _poll_job(
    client: TestClient,
    job_id: str,
    *,
    timeout_s: float = 5.0,
) -> dict:
    """Poll job status until terminal or timeout."""
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/ingest/jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"succeeded", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish; last={last}")


def test_ingest_full_sync_returns_counts(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    raw_file = config.raw_dir / "acme" / "p1" / "note" / "readme.md"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("# hello")

    ingest_run = IngestRunResult(
        ingested=[
            IngestResult(
                raw_path=raw_file,
                document=MagicMock(),
                processed=ProcessedPaths(
                    content_path=tmp_path / "data/processed/acme/p1/note/readme.md",
                    metadata_path=tmp_path / "data/processed/acme/p1/note/readme.meta.json",
                ),
            )
        ],
        skipped=[config.raw_dir / "acme/p1/note/old.md"],
        removed=[
            RemovedProcessed(
                content_path=tmp_path / "data/processed/acme/p1/note/stale.md",
                metadata_path=tmp_path / "data/processed/acme/p1/note/stale.meta.json",
                source_file="data/raw/acme/demo/p1/note/stale.md",
            )
        ],
    )
    index_result = IndexBuildResult(
        manifest=IndexManifest(
            version=1,
            built_at="2026-01-01T00:00:00Z",
            chunk_count=3,
            source_fingerprints={},
        ),
        chunk_count=3,
        indexed_documents=1,
        skipped_documents=0,
        removed_documents=0,
    )

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    with (
        patch("ee_wiki.api.routes.ingest.ingest_path", return_value=ingest_run) as mock_ingest,
        patch(
            "ee_wiki.api.routes.ingest.build_index_from_processed",
            return_value=index_result,
        ) as mock_index,
    ):
        response = client.post(
            "/v1/ingest",
            json={"product": "phone", "project": "acme", "build": "p1", "force": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingested"] == 1
    assert payload["skipped"] == 1
    assert payload["removed"] == 1
    assert payload["indexed_documents"] == 1
    assert payload["chunk_count"] == 3
    mock_ingest.assert_called_once_with(
        config.raw_dir / "phone" / "acme" / "p1",
        config,
        force=True,
    )
    mock_index.assert_called_once_with(config, force=True)


def test_ingest_only_skips_index(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    with (
        patch(
            "ee_wiki.api.routes.ingest.ingest_path",
            return_value=IngestRunResult(),
        ) as mock_ingest,
        patch("ee_wiki.api.routes.ingest.build_index_from_processed") as mock_index,
    ):
        response = client.post("/v1/ingest", json={"ingest_only": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["indexed_documents"] is None
    mock_ingest.assert_called_once()
    mock_index.assert_not_called()


def test_index_only_skips_ingest(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    index_result = IndexBuildResult(
        manifest=IndexManifest(
            version=1,
            built_at="",
            chunk_count=0,
            source_fingerprints={},
        ),
        chunk_count=0,
        indexed_documents=0,
        skipped_documents=2,
        removed_documents=0,
    )

    with (
        patch("ee_wiki.api.routes.ingest.ingest_path") as mock_ingest,
        patch(
            "ee_wiki.api.routes.ingest.build_index_from_processed",
            return_value=index_result,
        ) as mock_index,
    ):
        response = client.post("/v1/ingest", json={"index_only": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingested"] == 0
    assert payload["skipped_documents"] == 2
    mock_ingest.assert_not_called()
    mock_index.assert_called_once_with(config, force=False)


def test_conflicting_modes_return_400(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post(
        "/v1/ingest",
        json={"ingest_only": True, "index_only": True},
    )

    assert response.status_code == 400
    assert "ingest_only" in response.json()["detail"]


def test_missing_path_returns_404(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    with patch(
        "ee_wiki.api.routes.ingest.ingest_path",
        side_effect=IngestionError("Path does not exist: /tmp/missing"),
    ):
        response = client.post(
            "/v1/ingest",
            json={"path": "acme/p1/note/missing.md"},
        )

    assert response.status_code == 404


def test_path_outside_raw_dir_returns_400(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post("/v1/ingest", json={"path": "/etc/passwd"})

    assert response.status_code == 400
    assert "must be under" in response.json()["detail"]


def test_async_ingest_accepts_and_polls_until_done(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    index_result = IndexBuildResult(
        manifest=IndexManifest(
            version=1,
            built_at="2026-01-01T00:00:00Z",
            chunk_count=2,
            source_fingerprints={},
        ),
        chunk_count=2,
        indexed_documents=1,
        skipped_documents=0,
        removed_documents=0,
    )

    with (
        patch(
            "ee_wiki.api.routes.ingest.ingest_path",
            return_value=IngestRunResult(),
        ),
        patch(
            "ee_wiki.api.routes.ingest.build_index_from_processed",
            return_value=index_result,
        ),
    ):
        response = client.post(
            "/v1/ingest",
            json={"product": "phone", "project": "acme", "async": True},
        )
        assert response.status_code == 202
        accepted = response.json()
        assert accepted["status"] == "queued"
        assert accepted["job_id"]
        assert accepted["status_url"] == f"/v1/ingest/jobs/{accepted['job_id']}"

        final = _poll_job(client, accepted["job_id"])

    assert final["status"] == "succeeded"
    assert final["error"] is None
    assert final["result"] is not None
    assert final["result"]["indexed_documents"] == 1
    assert final["result"]["chunk_count"] == 2


def test_async_ingest_failure_sets_job_failed(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    with patch(
        "ee_wiki.api.routes.ingest.ingest_path",
        side_effect=IngestionError("Path does not exist: missing"),
    ):
        response = client.post(
            "/v1/ingest",
            json={"path": "acme/p1/note/missing.md", "async": True},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        final = _poll_job(client, job_id)

    assert final["status"] == "failed"
    assert final["result"] is None
    assert "does not exist" in (final["error"] or "")


def test_async_unknown_job_returns_404(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.get("/v1/ingest/jobs/not-a-real-job")
    assert response.status_code == 404


def test_async_conflicting_modes_rejected_before_accept(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post(
        "/v1/ingest",
        json={"ingest_only": True, "index_only": True, "async": True},
    )
    assert response.status_code == 400


def test_async_respects_max_concurrent_ingest_jobs(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    config.api.max_concurrent_ingest_jobs = 1
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    release = Event()
    started = Event()

    def _blocking_ingest(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5.0)
        return IngestRunResult()

    with (
        patch(
            "ee_wiki.api.routes.ingest.ingest_path",
            side_effect=_blocking_ingest,
        ),
        patch(
            "ee_wiki.api.routes.ingest.build_index_from_processed",
            return_value=IndexBuildResult(
                manifest=IndexManifest(
                    version=1,
                    built_at="",
                    chunk_count=0,
                    source_fingerprints={},
                ),
                chunk_count=0,
                indexed_documents=0,
                skipped_documents=0,
                removed_documents=0,
            ),
        ),
    ):
        first = client.post(
            "/v1/ingest",
            json={"ingest_only": True, "async": True},
        )
        assert first.status_code == 202
        assert started.wait(timeout=2.0)

        second = client.post(
            "/v1/ingest",
            json={"ingest_only": True, "async": True},
        )
        assert second.status_code == 202
        job2 = second.json()["job_id"]

        # Second job remains queued while the first holds the concurrency slot.
        status2 = client.get(f"/v1/ingest/jobs/{job2}").json()
        assert status2["status"] == "queued"

        release.set()
        final1 = _poll_job(client, first.json()["job_id"])
        final2 = _poll_job(client, job2)

    assert final1["status"] == "succeeded"
    assert final2["status"] == "succeeded"


def test_ingest_rejects_missing_api_key_when_configured(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    config.api.ingest_api_key = "secret-token"
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post("/v1/ingest", json={"ingest_only": True})

    assert response.status_code == 401
    assert "API key" in response.json()["detail"]


def test_ingest_rejects_wrong_api_key(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    config.api.ingest_api_key = "secret-token"
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post(
        "/v1/ingest",
        json={"ingest_only": True},
        headers={"X-API-Key": "wrong"},
    )

    assert response.status_code == 401


def test_ingest_accepts_x_api_key_header(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    config.api.ingest_api_key = "secret-token"
    empty = IngestRunResult(ingested=[], skipped=[], removed=[])

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    with patch("ee_wiki.api.routes.ingest.ingest_path", return_value=empty):
        response = client.post(
            "/v1/ingest",
            json={"ingest_only": True},
            headers={"X-API-Key": "secret-token"},
        )

    assert response.status_code == 200
    assert response.json()["ingested"] == 0


def test_ingest_accepts_bearer_and_protects_job_poll(tmp_path: Path) -> None:
    config = _mock_config(tmp_path)
    config.api.ingest_api_key = "secret-token"
    empty = IngestRunResult(ingested=[], skipped=[], removed=[])

    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)
    auth = {"Authorization": "Bearer secret-token"}

    with patch("ee_wiki.api.routes.ingest.ingest_path", return_value=empty):
        accepted = client.post(
            "/v1/ingest",
            json={"ingest_only": True, "async": True},
            headers=auth,
        )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]

    denied = client.get(f"/v1/ingest/jobs/{job_id}")
    assert denied.status_code == 401

    final = _poll_job_with_headers(client, job_id, headers=auth)
    assert final["status"] == "succeeded"


def _poll_job_with_headers(
    client: TestClient,
    job_id: str,
    *,
    headers: dict[str, str],
    timeout_s: float = 5.0,
) -> dict:
    """Poll job status with auth headers until terminal or timeout."""
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/ingest/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"succeeded", "failed"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish; last={last}")
