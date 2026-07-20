"""Tests for Open WebUI FA check-in / session-locked routing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.common.config import load_config
from ee_wiki.common.project_aliases import normalize_project_aliases
from ee_wiki.integrations.fa_chat import (
    awaiting_radar_id_from_history,
    fa_session_radar_id_from_history,
    parse_fa_checkin_radar_id,
    try_fa_chat_reply,
)
from ee_wiki.retrieval.rewrite import ConversationTurn


def test_parse_checkin_intents() -> None:
    assert parse_fa_checkin_radar_id("分析 radar 12345678") == "12345678"
    assert parse_fa_checkin_radar_id("new checkin rdar://87654321") == "87654321"
    assert parse_fa_checkin_radar_id("rdar://111222333") == "111222333"
    assert parse_fa_checkin_radar_id("帮我FA一下radar://123456") == "123456"
    assert parse_fa_checkin_radar_id("FA一下radar://55555666") == "55555666"
    assert parse_fa_checkin_radar_id("radar://123456帮我分析一下") == "123456"
    assert parse_fa_checkin_radar_id("帮我分析一下radar://123456") == "123456"
    assert parse_fa_checkin_radar_id("what is logan p1 lcd?") is None


def test_awaiting_radar_from_assistant_prompt() -> None:
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "## FA check-in — rdar://12345678\n\n"
                "### Need test evidence\n"
                "Flames API is not available — please paste either:\n"
            ),
        )
    ]
    assert awaiting_radar_id_from_history(history) == "12345678"
    assert fa_session_radar_id_from_history(history) == "12345678"


def test_try_fa_chat_checkin_then_session_lock(
    repo_root: Path, tmp_path: Path
) -> None:
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
                stub_component_version="P1",
            ),
        ),
        api=replace(config.api, public_base_url="http://ee-wiki.test:8080"),
    )

    first = try_fa_chat_reply(config, "帮忙分析 radar 42424242")
    assert first is not None
    assert "rdar://42424242" in first
    assert "Need test evidence" in first
    assert "product=`ipad`" in first
    assert "project=`logan`" in first

    history = [ConversationTurn(role="assistant", content=first)]

    # Without LLM: session stays locked (no RAG fallthrough).
    stay = try_fa_chat_reply(config, "STM32F407 核心参数", history)
    assert stay is not None
    assert "locked to the FA session" in stay
    assert "rdar://42424242" in stay

    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "KIND: stay"
    stay_llm = try_fa_chat_reply(
        config, "STM32F407 核心参数", history, llm=llm
    )
    assert stay_llm is not None
    assert "locked to the FA session" in stay_llm
    llm.generate.assert_called()

    llm.generate.return_value = "KIND: evidence"
    second = try_fa_chat_reply(
        config,
        "station: FQT\nERROR: VDD_CORE out of range\nFAIL: AAB\n",
        history,
        llm=llm,
    )
    assert second is not None
    assert "VDD_CORE" in second
    assert second.count("Fail items") >= 1


def test_non_fa_falls_through(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    assert try_fa_chat_reply(config, "logan p1 LCD pinout") is None
