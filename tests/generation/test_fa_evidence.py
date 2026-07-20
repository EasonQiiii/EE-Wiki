"""Tests for LLM Radar corpus → fail-item extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.generation.fa_evidence import (
    _parse_fail_items_output,
    extract_fail_items_from_radar_corpus,
)


def test_parse_fail_items_bullets() -> None:
    items = _parse_fail_items_output(
        "FAIL_ITEMS:\n- flash cannot erase fully\n- entering standby during test\n"
    )
    assert items is not None
    assert [i.message for i in items] == [
        "flash cannot erase fully",
        "entering standby during test",
    ]


def test_parse_fail_items_none() -> None:
    assert _parse_fail_items_output("FAIL_ITEMS: none") == []


def test_extract_calls_prompt(repo_root: Path) -> None:
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "FAIL_ITEMS:\n- Scarif flash cannot erase fully\n"
    )
    items = extract_fail_items_from_radar_corpus(
        "## Title\nRuby flash erase\n",
        llm=llm,
        repo_root=repo_root,
    )
    assert items is not None
    assert items[0].message.startswith("Scarif")
    prompt = llm.generate.call_args.args[0]
    assert "Ruby flash erase" in prompt
    assert "FAIL_ITEMS" in prompt
