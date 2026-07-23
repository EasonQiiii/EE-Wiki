"""Tests for request-scoped streaming status hub."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ee_wiki.api.stream_status import (
    FA_ATTACHMENT_ANALYZE_STATUS,
    FA_DOWNLOAD_STATUS,
    FA_FETCH_STATUS,
)
from ee_wiki.api.stream_status_context import (
    StreamStatusHub,
    bind_stream_status_emitter,
    push_stream_status,
)
from ee_wiki.common.config import load_config
from ee_wiki.integrations.radar.attachments import (
    format_attachment_content_markdown,
    materialize_named_attachments,
)


def test_push_stream_status_noop_without_binding() -> None:
    push_stream_status("should not raise")


def test_stream_status_hub_collects_updates() -> None:
    hub = StreamStatusHub()
    with bind_stream_status_emitter(hub.emit):
        push_stream_status(FA_FETCH_STATUS)
        push_stream_status(FA_DOWNLOAD_STATUS.format(done=1, total=3))
    assert hub.drain() == [
        FA_FETCH_STATUS,
        FA_DOWNLOAD_STATUS.format(done=1, total=3),
    ]
    assert hub.drain() == []


def test_materialize_named_attachments_emits_download_progress(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    hub = StreamStatusHub()
    names = [
        "sensor_flash_test_PASS_with_MLB_1.log",
        "sensor_flash_test_PASS_with_MLB_2.log",
    ]
    with bind_stream_status_emitter(hub.emit):
        successes, failures = materialize_named_attachments(
            config, "101493937", names
        )
    assert len(successes) == 2
    assert not failures
    progress = [s for s in hub.drain() if "正在下载附件" in s]
    assert progress == [
        FA_DOWNLOAD_STATUS.format(done=1, total=2),
        FA_DOWNLOAD_STATUS.format(done=2, total=2),
    ]


def test_content_markdown_emits_analyze_status(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    hub = StreamStatusHub()
    with bind_stream_status_emitter(hub.emit):
        md = format_attachment_content_markdown(
            config,
            "101493937",
            "分析 sensor_flash_test_PASS_with_MLB_1.log",
        )
    assert "Attachment content" in md
    assert hub.drain()[0] == FA_ATTACHMENT_ANALYZE_STATUS


def test_related_evidence_emits_download_progress(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    """Check-in strong-related materialize must push FA_DOWNLOAD_STATUS (n/m)."""
    from ee_wiki.integrations import session as session_mod
    from ee_wiki.protocols.radar import (
        AttachmentMeta,
        DiagnosisItem,
        RadarProblem,
    )

    problem = RadarProblem(
        radar_id="700002",
        title="two related logs",
        diagnosis=(
            DiagnosisItem(
                text="see a.log and b.log",
                added_by="e",
                entry_type="user",
            ),
        ),
        attachments=(
            AttachmentMeta(file_name="a.log", kind="attachment"),
            AttachmentMeta(file_name="b.log", kind="attachment"),
        ),
    )

    class _Radar:
        def download_attachment(self, radar_id, file_name, *, dest_path):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(f"FAIL: {file_name}\n", encoding="utf-8")
            return dest_path

        def download_picture(self, radar_id, file_name, *, dest_path):
            return self.download_attachment(
                radar_id, file_name, dest_path=dest_path
            )

    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    monkeypatch.setattr(
        "ee_wiki.integrations.radar.attachments.build_radar_backend",
        lambda cfg: _Radar(),
    )
    hub = StreamStatusHub()
    with bind_stream_status_emitter(hub.emit):
        related = session_mod._materialize_related_evidence(
            config,
            problem,
            ("a.log", "b.log"),
            cancel_event=None,
        )
    assert len(related.files) == 2
    assert hub.drain() == [
        FA_DOWNLOAD_STATUS.format(done=1, total=2),
        FA_DOWNLOAD_STATUS.format(done=2, total=2),
    ]