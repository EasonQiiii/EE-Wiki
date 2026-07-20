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
                {"demo_product": "logan", "H340": "logan"}
            ),
        ),
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="stub"),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    result = start_fa_checkin(config, "rdar://12345678")

    assert result.radar_id == "12345678"
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
                {"demo_product": "logan", "H340": "logan"}
            ),
        ),
        fa=replace(
            config.fa,
            flames=replace(config.fa.flames, backend="manual"),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    first = start_fa_checkin(config, "888001")
    assert first.awaiting_user_evidence is True
    assert first.fail_items.fail_items == ()
    assert "Need test evidence" in first.summary_markdown

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
    repo_root: Path, tmp_path: Path
) -> None:
    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        exports_dir=tmp_path / "exports",
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    report, url = generate_fa_summary(
        config,
        "5556677",
        project="logan",
        build="p1",
        fail_items=("VDD_CORE OOR",),
        steps=("X-ray OK", "T/A pending"),
    )

    assert report.output_path.is_file()
    assert report.download_rel_path == "fa/5556677/FA_summary.key"
    assert url == "http://ee-wiki.test:8080/v1/exports/fa/5556677/FA_summary.key"
