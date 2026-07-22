"""Unit tests for the history-embedded TurnScope marker (ADR 0012 §6).

The marker lets a follow-up with no scope words inherit the prior turn's locked
TurnScope without any per-process shared store, so it survives ``uvicorn
--workers N``. These tests cover formatting, parsing from history, and the
chunk-appending helper.
"""

from __future__ import annotations

from ee_wiki.api.scope_marker import (
    CarriedScope,
    append_scope_marker,
    format_scope_marker,
    parse_scope_marker,
)
from ee_wiki.retrieval.rewrite import ConversationTurn


def test_carried_scope_properties() -> None:
    complete = CarriedScope("ipad", "logan", "p1")
    assert complete.complete is True
    assert complete.empty is False

    partial = CarriedScope(None, "logan", "p1")
    assert partial.complete is False
    assert partial.empty is False

    none = CarriedScope(None, None, None)
    assert none.complete is False
    assert none.empty is True


def test_format_scope_marker_full() -> None:
    marker = format_scope_marker("ipad", "logan", "p1")
    assert marker == "<!-- ee-wiki-scope: ipad/logan/p1 -->"


def test_format_scope_marker_encodes_missing_axes_as_dash() -> None:
    marker = format_scope_marker(None, "logan", None)
    assert marker == "<!-- ee-wiki-scope: -/logan/- -->"


def test_parse_scope_marker_recovers_full_triple() -> None:
    history = [
        ConversationTurn(role="user", content="logan p1 原理图有哪些电源轨？"),
        ConversationTurn(
            role="assistant",
            content="Reply text.<!-- ee-wiki-scope: ipad/logan/p1 -->",
        ),
    ]
    carried = parse_scope_marker(history)
    assert carried == CarriedScope("ipad", "logan", "p1")


def test_parse_scope_marker_normalizes_dash_to_none() -> None:
    history = [
        ConversationTurn(
            role="assistant",
            content="Reply.<!-- ee-wiki-scope: -/logan/- -->",
        )
    ]
    carried = parse_scope_marker(history)
    assert carried == CarriedScope(None, "logan", None)


def test_parse_scope_marker_uses_most_recent_assistant_turn() -> None:
    history = [
        ConversationTurn(
            role="assistant",
            content="Old.<!-- ee-wiki-scope: ipad/logan/p1 -->",
        ),
        ConversationTurn(role="user", content="follow-up"),
        ConversationTurn(
            role="assistant",
            content="New.<!-- ee-wiki-scope: iphone/ruby/p2 -->",
        ),
    ]
    carried = parse_scope_marker(history)
    assert carried == CarriedScope("iphone", "ruby", "p2")


def test_parse_scope_marker_returns_none_when_absent() -> None:
    history = [
        ConversationTurn(role="user", content="logan p1?"),
        ConversationTurn(role="assistant", content="No marker here."),
    ]
    assert parse_scope_marker(history) is None


def test_parse_scope_marker_skips_user_turns_with_marker() -> None:
    # A marker-shaped string in a user turn must NOT be recovered.
    history = [
        ConversationTurn(
            role="user",
            content="<!-- ee-wiki-scope: ipad/logan/p1 -->",
        )
    ]
    assert parse_scope_marker(history) is None


def test_parse_scope_marker_empty_history_is_none() -> None:
    assert parse_scope_marker([]) is None


def test_append_scope_marker_yields_chunks_then_marker() -> None:
    chunks = iter(["a", "b"])
    marker = "<!-- ee-wiki-scope: ipad/logan/p1 -->"
    out = list(append_scope_marker(chunks, marker))
    assert out == ["a", "b", marker]
