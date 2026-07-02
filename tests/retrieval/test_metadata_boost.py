"""Tests for metadata keyword boosts."""

from __future__ import annotations

from ee_wiki.retrieval.metadata_boost import metadata_keyword_boost

_MODULE_A = "DISPLAY&SENSOR"
_PREFIX_A = "IFACE"
_MODULE_B = "COMM&USB"


def test_metadata_keyword_boost_matches_interfaces() -> None:
    metadata = {
        "interfaces": [_MODULE_A, _PREFIX_A, _MODULE_B],
        "nets": ["IFACE_D0", "IFACE_D1"],
    }
    score = metadata_keyword_boost(metadata, ["module_x", "proj_a"])
    assert score == 0


def test_metadata_keyword_boost_matches_module_token() -> None:
    metadata = {
        "interfaces": [_MODULE_A, _PREFIX_A],
        "nets": ["IFACE_D0"],
    }
    score = metadata_keyword_boost(metadata, ["display", "sensor"])
    assert score >= 1


def test_metadata_keyword_boost_zero_when_no_terms() -> None:
    assert metadata_keyword_boost({"interfaces": [_PREFIX_A]}, []) == 0
