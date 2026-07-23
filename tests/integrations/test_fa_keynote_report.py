"""Unit tests for Radar-grounded FA Keynote one-pager formatting / export."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.integrations.report.keynote import (
    StubKeynoteFaReportBackend,
    build_conclusion_from_radar,
    format_one_pager_markdown,
    format_slide_body,
)
from ee_wiki.integrations.session import generate_fa_summary
from ee_wiki.protocols.fa_report import FaReportRequest


def test_format_one_pager_has_summary_steps_conclusion() -> None:
    req = FaReportRequest(
        radar_id="182787079",
        product="iphone",
        project="logan",
        build="p1",
        title="IMU cal OOL",
        state="Analyze",
        substate="Screen",
        fail_items=("[bench] Gyro_Y OOL",),
        steps=("Bench Cal_LPNM 3x reproduce", "Propose knock test"),
        conclusion="Ticket state: Analyze / Screen. Latest diagnosis: Propose knock test",
    )
    md = format_one_pager_markdown(req)
    assert "| Radar | `rdar://182787079` |" in md
    assert "| Project | logan |" in md
    assert "## FA Steps" in md
    assert "Bench Cal_LPNM 3x reproduce" in md
    assert "## Conclusion" in md
    assert "Propose knock test" in md
    body = format_slide_body(req)
    assert "rdar://182787079" in body
    assert "Conclusion (latest status)" in body


def test_build_conclusion_from_radar_no_invention() -> None:
    text = build_conclusion_from_radar(
        state="Analyze",
        substate="Screen",
        latest_diagnosis="Please perform CT scan after knock test.",
        fail_items=(),
    )
    assert "Analyze / Screen" in text
    assert "CT scan" in text
    assert "root cause" not in text.lower()


def test_generate_fa_summary_writes_md_only_on_text_fallback(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        exports_dir=tmp_path / "exports",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    backend = StubKeynoteFaReportBackend(
        exports_dir=config.exports_dir,
        force_text_fallback=True,
    )
    report = backend.generate(
        FaReportRequest(
            radar_id="5556677",
            product="iphone",
            project="logan",
            build="p1",
            title="Scarif flash",
            state="Verify",
            steps=("X-ray OK", "T/A pending"),
            conclusion="Ticket state: Verify. Latest diagnosis: T/A pending",
        )
    )
    md = config.exports_dir / "fa/5556677/FA_summary.md"
    key = config.exports_dir / "fa/5556677/FA_summary.key"
    assert report.output_path == md
    assert md.is_file()
    assert not key.exists()
    assert report.keynote_available is False
    assert report.download_rel_path == "fa/5556677/FA_summary.md"
    text = md.read_text(encoding="utf-8")
    assert "rdar://5556677" in text
    assert "T/A pending" in text
    assert "Conclusion" in text


def test_generate_fa_summary_removes_stale_fake_key_on_fallback(
    repo_root: Path, tmp_path: Path
) -> None:
    """Re-export after a prior text-as-.key bug must not leave a broken .key."""
    config = load_config(repo_root=repo_root)
    config = replace(config, exports_dir=tmp_path / "exports")
    key = config.exports_dir / "fa/5556677/FA_summary.key"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text("# old fake markdown key\n", encoding="utf-8")

    backend = StubKeynoteFaReportBackend(
        exports_dir=config.exports_dir,
        force_text_fallback=True,
    )
    report = backend.generate(
        FaReportRequest(
            radar_id="5556677",
            title="Scarif flash",
            steps=("X-ray OK",),
            conclusion="Ticket state: Verify.",
        )
    )
    assert not key.exists()
    assert report.output_path.name == "FA_summary.md"


def test_generate_fa_summary_download_url_via_session(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    from ee_wiki.integrations import factory as factory_mod

    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        exports_dir=tmp_path / "exports",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    def _backend(cfg):
        return StubKeynoteFaReportBackend(
            exports_dir=cfg.exports_dir,
            force_text_fallback=True,
        )

    monkeypatch.setattr(factory_mod, "build_fa_report_backend", _backend)
    report, url = generate_fa_summary(
        config,
        "5556677",
        product="iphone",
        project="logan",
        build="p1",
        fail_items=("VDD_CORE OOR",),
        steps=("X-ray OK", "T/A pending"),
        state="Analyze",
        conclusion="Ticket state: Analyze. Latest diagnosis: T/A pending",
    )
    assert report.output_path.is_file()
    assert report.download_rel_path == "fa/5556677/FA_summary.md"
    assert url == "http://ee-wiki.test:8080/v1/exports/fa/5556677/FA_summary.md"
    assert report.keynote_available is False
    assert "T/A pending" in report.output_path.read_text(encoding="utf-8")
