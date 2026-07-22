"""Proactive FA entry / scope / bind regression matrix.

These cases exist so lab users do not rediscover paste-format and scope bugs.
Angles covered (add here when a new real-world paste fails):

1. Radar URL shapes humans actually paste (problem/, angle brackets, Chinese glue)
2. Mode gate still FA without LLM when a structural URL is present
3. ensure_fa_session binds (never stays unbound) when a URL is present
4. Canonical stub check-in resolves EE-Wiki scope (not product=? project=?)
5. Unbound → bind on a later ``rdar://problem/…`` turn
6. FaAgent.handle with a problem URL takes the **bound** path (not engineering_search)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ee_wiki.agents.fa_agent import FaAgent
from ee_wiki.agents.fa_mode import resolve_chat_mode
from ee_wiki.agents.fa_session import ensure_fa_session, unbound_header_markdown
from ee_wiki.common.config import load_config
from ee_wiki.integrations.fa_chat import parse_fa_checkin_radar_id
from ee_wiki.integrations.session import start_fa_checkin
from ee_wiki.retrieval.rewrite import ConversationTurn
from ee_wiki.tools.bus import ToolBus

# Realistic pastes observed / anticipated in Open WebUI (not an exhaustive RFC).
_RADAR_PASTE_CASES: list[tuple[str, str]] = [
    ("rdar://101493937", "101493937"),
    ("radar://101493937", "101493937"),
    ("rdar://problem/101493937", "101493937"),
    ("radar://problem/101493937", "101493937"),
    ("帮我看下rdar://problem/101493937咯", "101493937"),
    ("看下这个 <rdar://problem/101493937>", "101493937"),
    ("FA一下 rdar://problem/101493937", "101493937"),
    ("new checkin rdar://problem/88800122", "88800122"),
    ("radar 101493937", "101493937"),
    ("分析 radar 101493937", "101493937"),
    # Trailing punctuation / chat fluff
    ("rdar://problem/101493937。", "101493937"),
    ("rdar://problem/101493937?", "101493937"),
    ("请看 rdar://problem/101493937 谢谢", "101493937"),
]


@pytest.mark.parametrize(("text", "expected"), _RADAR_PASTE_CASES)
def test_parse_radar_paste_shapes(text: str, expected: str) -> None:
    assert parse_fa_checkin_radar_id(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "what is logan p1 lcd?",
        "STM32F407 核心参数",
        "VDD_1V8 电源树",
        "problem/101493937",  # path alone without scheme — not a Radar URL
        "rdar://",  # incomplete
    ],
)
def test_parse_rejects_non_radar(text: str) -> None:
    assert parse_fa_checkin_radar_id(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "帮我看下rdar://problem/101493937咯",
        "rdar://problem/101493937",
        "<rdar://problem/101493937>",
    ],
)
def test_mode_is_fa_for_problem_url_without_llm(repo_root: Path, text: str) -> None:
    """Structural URL must enter FaMode even when classify LLM is absent."""
    config = load_config(repo_root=repo_root)
    assert (
        resolve_chat_mode(text, history=None, llm=None, config=config) == "fa"
    )


@pytest.mark.parametrize(
    "text",
    [
        "帮我看下rdar://problem/101493937咯",
        "rdar://problem/101493937",
    ],
)
def test_ensure_session_binds_on_problem_url(repo_root: Path, text: str) -> None:
    config = load_config(repo_root=repo_root)
    session = ensure_fa_session(text, None, None, None, None, config=config)
    assert session.bound is True
    assert session.radar_id == "101493937"
    assert session.unbound is False


def test_canonical_stub_checkin_has_real_scope_not_question_marks(
    repo_root: Path, tmp_path: Path
) -> None:
    """Lab gold: problem URL check-in must not leave product=? project=?."""
    from dataclasses import replace

    config = load_config(repo_root=repo_root)
    config = replace(config, cache_dir=tmp_path / "cache")
    result = start_fa_checkin(config, "帮我看下rdar://problem/101493937咯")
    assert result.radar_id == "101493937"
    assert result.scope.product == "ipad"
    assert result.scope.project == "logan"
    assert result.scope.build == "p0"
    assert "product=`?`" not in result.summary_markdown
    assert "project=`?`" not in result.summary_markdown
    assert "## FA check-in — rdar://101493937" in result.summary_markdown


def test_unbound_then_bind_with_problem_url(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    unbound = ensure_fa_session(
        "帮我FA一下为什么U8600（logan p1）的IIC接口没有输出",
        None,
        "ipad",
        "logan",
        "p1",
        config=config,
    )
    assert unbound.bound is False
    history = [
        ConversationTurn(
            role="assistant",
            content=unbound_header_markdown(unbound),
        )
    ]
    bound = ensure_fa_session(
        "帮我看下rdar://problem/101493937咯",
        history,
        "ipad",
        "logan",
        "p1",
        config=config,
    )
    assert bound.bound is True
    assert bound.radar_id == "101493937"


def test_fa_agent_problem_url_uses_bound_path_not_unbound_search(
    repo_root: Path, tmp_path: Path
) -> None:
    """Must not dump unbound Tool evidence / engineering_search for a ticket URL."""
    from dataclasses import replace

    config = load_config(repo_root=repo_root)
    config = replace(config, cache_dir=tmp_path / "cache")
    bus = MagicMock(spec=ToolBus)
    agent = FaAgent(config, bus, llm=None)
    result = agent.handle("帮我看下rdar://problem/101493937咯")
    assert result.branch in {"respond", "fa_agent"}
    assert "## FA check-in — rdar://101493937" in result.markdown
    assert "FA（未绑定 Radar）" not in result.markdown
    assert "### Tool evidence" not in result.markdown
    # Bound path talks to Radar/session helpers, not the unbound skill bus.
    bus.call.assert_not_called()
