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
    # Structural token alone — no verb required (Open WebUI casual phrasing).
    assert parse_fa_checkin_radar_id("看下这个，朋友，radar://123456") == "123456"
    assert parse_fa_checkin_radar_id("朋友 rdar://99999888") == "99999888"
    # Real Radar web URL format carries a `problem/` path segment.
    assert parse_fa_checkin_radar_id("帮我看下rdar://problem/101493937咯") == "101493937"
    assert parse_fa_checkin_radar_id("rdar://problem/888001") == "888001"
    assert parse_fa_checkin_radar_id("<rdar://problem/101493937>") == "101493937"
    assert parse_fa_checkin_radar_id("what is logan p1 lcd?") is None


def test_canonical_stub_scope_from_aliases(repo_root: Path) -> None:
    """rdar://101493937 stub must resolve EE-Wiki scope via aliases (not ?/?)."""
    from ee_wiki.integrations.session import start_fa_checkin

    config = load_config(repo_root=repo_root)
    result = start_fa_checkin(config, "rdar://problem/101493937")
    assert result.radar_id == "101493937"
    assert result.scope.project == "logan"
    assert result.scope.product == "ipad"
    assert result.scope.build == "p0"
    assert "project=`logan`" in result.summary_markdown
    assert "product=`?`" not in result.summary_markdown


def test_supervisor_forces_radar_on_casual_radar_url(repo_root: Path) -> None:
    """Casual phrasing with radar:// must not fall through to hybrid RAG."""
    from unittest.mock import MagicMock

    from ee_wiki.agents.roles import load_all_roles
    from ee_wiki.agents.supervisor import Supervisor
    from ee_wiki.tools.bus import ToolBus

    config = load_config(repo_root=repo_root)
    roles = load_all_roles(config.agents_roles_dir)
    bus = MagicMock(spec=ToolBus)
    bus.call.return_value = MagicMock(
        ok=True,
        text="## FA check-in — rdar://123456\n\nstub",
        error=None,
    )
    sup = Supervisor(config, bus, roles)
    result = sup.handle("看下这个，朋友，radar://123456")
    assert result.kind == "respond"
    assert "FA check-in" in result.markdown
    assert "Agent evidence" not in result.markdown
    bus.call.assert_called_once()


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

    # Without LLM: short follow-ups are FA dialogue (not rigid paste nag).
    next_step = try_fa_chat_reply(config, "下一步是什么", history)
    assert next_step is not None
    assert "rdar://42424242" in next_step
    assert "locked to the FA session" not in next_step

    checkin_with_atts = (
        "## FA check-in — rdar://42424242\n\n"
        "**Radar attachments:** `UNIT_save_100_NG.log`, `UNIT_save_500_NG.log`\n\n"
        "### Fail items\n"
        "- [radar] flash erase incomplete\n"
    )
    log_q = try_fa_chat_reply(
        config,
        "radar里没有log吗",
        [ConversationTurn(role="assistant", content=checkin_with_atts)],
    )
    assert log_q is not None
    assert "UNIT_save_100_NG.log" in log_q
    assert "没有把" in log_q or "正文" in log_q

    # Off-topic wiki ask with LLM stay → redirect, still FA-bound.
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "KIND: stay"
    stay_llm = try_fa_chat_reply(
        config, "STM32F407 核心参数", history, llm=llm
    )
    assert stay_llm is not None
    assert "rdar://42424242" in stay_llm
    assert "新开" in stay_llm or "wiki" in stay_llm.lower()
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
