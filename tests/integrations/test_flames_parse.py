"""Tests for shared Flames log / paste error extraction."""

from __future__ import annotations

from ee_wiki.integrations.flames.parse import extract_errors_from_text


def test_extracts_error_and_fail_lines() -> None:
    text = "INFO ok\nERROR: rail OOR\nFAIL: AAB\n"
    items = extract_errors_from_text(text)
    assert [i.message for i in items] == ["rail OOR", "AAB"]


def test_extracts_bullet_list_when_no_error_prefix() -> None:
    text = "- first fail\n* second fail\n1. third fail\n"
    items = extract_errors_from_text(text)
    assert len(items) == 3
    assert items[0].message == "first fail"


def test_single_line_paste() -> None:
    items = extract_errors_from_text("VDD_CORE out of range")
    assert len(items) == 1
    assert "VDD_CORE" in items[0].message
