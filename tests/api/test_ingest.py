"""Tests for admin ingest API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config
from ee_wiki.ingestion.cleanup import RemovedProcessed
from ee_wiki.ingestion.pipeline import IngestionError, IngestResult, IngestRunResult
from ee_wiki.knowledge.indexer.build import IndexBuildResult
from ee_wiki.knowledge.indexer.store import IndexManifest
from ee_wiki.knowledge.store.processed import ProcessedPaths


def _mock_config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.raw_dir = tmp_path / "data" / "raw"
    config.repo_root = tmp_path
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    return config


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
                source_file="data/raw/acme/p1/note/stale.md",
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
            json={"project": "acme", "build": "p1", "force": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingested"] == 1
    assert payload["skipped"] == 1
    assert payload["removed"] == 1
    assert payload["indexed_documents"] == 1
    assert payload["chunk_count"] == 3
    mock_ingest.assert_called_once_with(
        config.raw_dir / "acme" / "p1",
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
