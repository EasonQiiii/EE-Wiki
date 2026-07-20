"""Tests for serve-time lab readiness warnings."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ee_wiki.api.startup_checks import warn_lab_readiness
from ee_wiki.common.config import load_config


def test_warns_when_schematic_pdf_lacks_netlist(
    repo_root: Path, tmp_path: Path, caplog
) -> None:
    config = load_config(repo_root=repo_root)
    raw = tmp_path / "raw"
    sch = raw / "iphone" / "logan" / "p1" / "sch"
    sch.mkdir(parents=True)
    (sch / "board.pdf").write_bytes(b"%PDF-1.4")
    config = replace(
        config,
        raw_dir=raw,
        processed_dir=tmp_path / "processed",
        indexes_dir=tmp_path / "indexes",
    )
    (tmp_path / "indexes").mkdir()

    with caplog.at_level("WARNING"):
        warn_lab_readiness(config)

    text = "\n".join(r.message for r in caplog.records)
    assert "no netlist companion" in text
    assert "board.pdf" in text
    assert "no SOP" in text or "station" in text.lower()


def test_no_netlist_warning_when_dot_net_present(
    repo_root: Path, tmp_path: Path, caplog
) -> None:
    config = load_config(repo_root=repo_root)
    raw = tmp_path / "raw"
    sch = raw / "iphone" / "logan" / "p1" / "sch"
    sch.mkdir(parents=True)
    (sch / "board.pdf").write_bytes(b"%PDF-1.4")
    (sch / "board.net").write_text("NET1 U1 1\n", encoding="utf-8")
    sop = raw / "iphone" / "logan" / "p1" / "sop" / "stations"
    sop.mkdir(parents=True)
    (sop / "station_a.md").write_text("# A\n", encoding="utf-8")
    indexes = tmp_path / "indexes"
    indexes.mkdir()
    (indexes / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
    config = replace(
        config,
        raw_dir=raw,
        processed_dir=tmp_path / "processed",
        indexes_dir=indexes,
    )

    with caplog.at_level("WARNING"):
        warn_lab_readiness(config)

    text = "\n".join(r.message for r in caplog.records)
    assert "no netlist companion" not in text
