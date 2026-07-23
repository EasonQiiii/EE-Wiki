"""Tests for FA check-in orchestration with stub / manual Flames backends."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import IntegrationError
from ee_wiki.common.project_aliases import normalize_project_aliases
from ee_wiki.integrations.session import (
    commit_diagnosis,
    generate_fa_summary,
    ingest_fa_user_evidence,
    start_fa_checkin,
)


def test_start_fa_checkin_lists_fail_items_and_logs(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        exports_dir=tmp_path / "exports",
        data_layout=replace(
            config.data_layout,
            project_aliases=normalize_project_aliases(
                {
                    "demo_product": "ipad/logan",
                    "H340": "ipad/logan",
                }
            ),
        ),
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="stub"),
            radar=replace(
                config.fa.radar,
                stub_component_name="ipad/logan",
                stub_component_version="P1",
            ),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    result = start_fa_checkin(config, "rdar://12345678")

    assert result.radar_id == "12345678"
    assert result.scope.product == "ipad"
    assert result.scope.project == "logan"
    assert result.scope.build == "p1"
    assert result.awaiting_user_evidence is False
    assert len(result.fail_items.fail_items) >= 2
    assert result.log_download_urls
    assert result.log_download_urls[0].startswith(
        "http://ee-wiki.test:8080/v1/cache/fa/12345678/"
    )
    assert "Fail items" in result.summary_markdown
    assert (tmp_path / "cache/fa/12345678").is_dir()


def test_manual_checkin_awaits_then_ingests_paste(
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        data_layout=replace(
            config.data_layout,
            project_aliases=normalize_project_aliases(
                {
                    "demo_product": "ipad/logan",
                    "H340": "ipad/logan",
                }
            ),
        ),
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="manual"),
            radar=replace(
                config.fa.radar,
                stub_component_name="ipad/logan",
                stub_component_version="P1",
            ),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    # No LLM: Radar corpus exists on stub but cannot be extracted → ask user.
    first = start_fa_checkin(config, "888001")
    assert first.awaiting_user_evidence is True
    assert first.fail_items.fail_items == ()
    assert "Need test evidence" in first.summary_markdown
    assert "Radar has title/description/diagnosis" in first.summary_markdown
    assert "H9H242500041JJY1A_save_100_NG.log" in first.summary_markdown
    assert first.scope.product == "ipad"
    assert first.scope.project == "logan"
    assert (tmp_path / "cache/fa/888001/radar_corpus.txt").is_file()

    second = ingest_fa_user_evidence(
        config,
        "888001",
        "ERROR: VDD_CORE out of range\nFAIL: AAB retry limit\n",
        station="FQT",
    )
    assert second.awaiting_user_evidence is False
    assert len(second.fail_items.fail_items) >= 2
    assert second.log_download_urls
    assert "VDD_CORE" in second.summary_markdown
    assert (tmp_path / "cache/fa/888001/user_fqt.log").is_file()


def test_manual_checkin_extracts_radar_with_llm(
    repo_root: Path, tmp_path: Path
) -> None:
    from unittest.mock import MagicMock

    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        data_layout=replace(
            config.data_layout,
            project_aliases=normalize_project_aliases(
                {"demo_product": "ipad/logan"}
            ),
        ),
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="manual"),
            radar=replace(
                config.fa.radar,
                stub_component_name="ipad/logan",
                stub_component_version="P0",
            ),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "FAIL_ITEMS:\n"
        "- Scarif flash cannot erase fully after imu save\n"
        "- system entering standby during test\n"
    )

    result = start_fa_checkin(config, "101493937", llm=llm)
    assert result.awaiting_user_evidence is False
    assert result.fail_items.source == "radar"
    assert len(result.fail_items.fail_items) == 2
    # V2 template drops the "Evidence source" line; source still resolved.
    assert "**Evidence source:**" not in result.summary_markdown
    assert "flash cannot erase" in result.summary_markdown.lower()


def test_manual_accepts_bullet_list(repo_root: Path, tmp_path: Path) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="manual"),
        ),
    )

    result = ingest_fa_user_evidence(
        config,
        "888002",
        "- rail droop on VDD_SOC\n- I2C NACK on U12\n",
    )
    assert result.awaiting_user_evidence is False
    messages = [item.message for item in result.fail_items.fail_items]
    assert any("VDD_SOC" in m for m in messages)
    assert any("I2C" in m for m in messages)


def test_ingest_requires_manual_backend(repo_root: Path, tmp_path: Path) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        cache_dir=tmp_path / "cache",
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="stub"),
        ),
    )
    with pytest.raises(IntegrationError, match="manual"):
        ingest_fa_user_evidence(config, "1", "ERROR: x")


def test_diagnosis_requires_confirm(repo_root: Path, tmp_path: Path) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(config, cache_dir=tmp_path / "cache")

    draft = commit_diagnosis(
        config, "999001", "draft note", confirm=False
    )
    assert draft.committed is False
    assert draft.draft_preview == "draft note"

    committed = commit_diagnosis(
        config, "999001", "committed note", confirm=True
    )
    assert committed.committed is True


def test_generate_fa_summary_download_url(
    repo_root: Path, tmp_path: Path, monkeypatch
) -> None:
    from ee_wiki.integrations import factory as factory_mod
    from ee_wiki.integrations.report.keynote import StubKeynoteFaReportBackend

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
        project="logan",
        build="p1",
        fail_items=("VDD_CORE OOR",),
        steps=("X-ray OK", "T/A pending"),
        conclusion="Ticket state: Analyze. Latest diagnosis: T/A pending",
    )

    assert report.output_path.is_file()
    assert report.download_rel_path == "fa/5556677/FA_summary.md"
    assert url == "http://ee-wiki.test:8080/v1/exports/fa/5556677/FA_summary.md"
    assert report.keynote_available is False
