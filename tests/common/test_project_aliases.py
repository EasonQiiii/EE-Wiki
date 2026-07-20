"""Tests for project alias normalization."""

from __future__ import annotations

from ee_wiki.common.project_aliases import (
    canonicalize_project,
    match_project_in_text,
    normalize_project_aliases,
)


def test_normalize_and_canonicalize() -> None:
    aliases = normalize_project_aliases({"H340": "logan", " h340 ": "Logan"})
    assert aliases == {"h340": "logan"}
    assert canonicalize_project("H340", aliases) == "logan"
    assert canonicalize_project("logan", aliases) == "logan"


def test_match_either_name_in_text() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    assert match_project_in_text("please check H340 p1", aliases) == "logan"
    assert match_project_in_text("Logan schematic", aliases) == "logan"
    assert match_project_in_text("no product here", aliases) is None
