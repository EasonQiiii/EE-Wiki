"""Tests for FA mode gating: resolve_chat_mode (fa-session.md A/B/C).

Verifies the decision order:
1. Structural Radar id in the question -> fa
2. Wiki connectivity (完整trace / 追网, no failure cues) -> wiki
3. History already an FA session (bound or unbound header) -> fa
4. LLM classify -> fa | wiki
5. No LLM / classify failed -> wiki (conservative default)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.agents.fa_mode import (
    is_fa_advice_without_investigation,
    is_wiki_connectivity_query,
    resolve_chat_mode,
)
from ee_wiki.common.config import load_config
from ee_wiki.retrieval.rewrite import ConversationTurn


def _config(repo_root: Path):
    """Load config with fa.enabled=True (the shipped default)."""
    config = load_config(repo_root=repo_root)
    assert config.fa.enabled is True
    return config


# ── 1. Structural Radar id in question -> fa (no LLM needed) ──────────────


def test_radar_url_in_question_is_fa_without_llm(repo_root: Path) -> None:
    """parse_fa_checkin_radar_id matches radar:// — no LLM required."""
    config = _config(repo_root)
    mode = resolve_chat_mode(
        "radar://101493937",
        history=None,
        llm=None,
        config=config,
    )
    assert mode == "fa"


def test_rdar_url_in_question_is_fa_without_llm(repo_root: Path) -> None:
    config = _config(repo_root)
    mode = resolve_chat_mode(
        "看下这个 rdar://99999888",
        history=None,
        llm=None,
        config=config,
    )
    assert mode == "fa"


def test_radar_keyword_with_digits_is_fa(repo_root: Path) -> None:
    config = _config(repo_root)
    mode = resolve_chat_mode(
        "帮我分析 radar 12345678",
        history=None,
        llm=None,
        config=config,
    )
    assert mode == "fa"


# ── 2. Wiki connectivity overrides FA sticky / LLM ────────────────────────


def test_schematic_full_trace_is_wiki_not_fa(repo_root: Path) -> None:
    """logan p1 原理图 … 完整trace must not open unbound FA as a symptom."""
    config = _config(repo_root)
    q = "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"
    assert is_wiki_connectivity_query(q)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: fa"
    mode = resolve_chat_mode(q, history=None, llm=llm, config=config)
    assert mode == "wiki"
    llm.generate.assert_not_called()


def test_full_trace_escapes_sticky_unbound_fa_history(repo_root: Path) -> None:
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content="**FA（未绑定 Radar）：** something",
        ),
    ]
    mode = resolve_chat_mode(
        "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace",
        history=history,
        llm=None,
        config=config,
    )
    assert mode == "wiki"


def test_trace_with_failure_language_stays_eligible_for_fa(
    repo_root: Path,
) -> None:
    """Failure cues keep the query out of the wiki-connectivity override."""
    assert not is_wiki_connectivity_query(
        "logan p1 DP_xxx 完整trace 为什么异常没输出"
    )


def test_trace_property_followup_is_wiki_not_fa(repo_root: Path) -> None:
    """Follow-up '这个trace的阻抗要求…等长布线' is a schematic/SI property ask,
    not an FA session — even if the LLM over-classifies it as fa.

    Repro: a trace refusal (no CAD netlist) was followed by '这个trace的阻抗
    要求是多少？是否需要等长布线？', which wrongly opened an unbound FA session.
    """
    config = _config(repo_root)
    q = "这个trace的阻抗要求是多少？是否需要等长布线？"
    assert is_wiki_connectivity_query(q)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: fa"  # simulate LLM over-classification
    mode = resolve_chat_mode(q, history=None, llm=llm, config=config)
    assert mode == "wiki"
    llm.generate.assert_not_called()  # structural guard short-circuits before LLM


def test_trace_property_with_failure_cue_stays_fa_eligible(repo_root: Path) -> None:
    """Failure language still beats the SI-property guard."""
    assert not is_wiki_connectivity_query(
        "这个trace阻抗异常，为什么没输出"
    )


def test_fa_methodology_advice_routes_to_wiki(repo_root: Path) -> None:
    """'这个trace没有输出应该怎么FA' asks ABOUT the FA process (methodology),
    not launching a real investigation — route to readable Wiki, not the heavy
    unbound FAQ artifact. Even when an LLM would over-classify it as fa."""
    config = _config(repo_root)
    q = "这个trace没有输出应该怎么FA"
    assert is_fa_advice_without_investigation(q)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: fa"  # simulate LLM over-classification
    mode = resolve_chat_mode(q, history=None, llm=llm, config=config)
    assert mode == "wiki"
    llm.generate.assert_not_called()  # structural advice gate short-circuits


def test_fa_advice_with_real_investigation_stays_fa(repo_root: Path) -> None:
    """'帮我FA这个trace，它没输出' is a real investigation, not advice — stays FA."""
    q = "帮我FA一下为什么U8600（logan p1）的IIC接口没有输出"
    assert not is_fa_advice_without_investigation(q)


# ── 3. History is an FA session -> fa ─────────────────────────────────────


def test_history_bound_checkin_header_is_fa(repo_root: Path) -> None:
    """Assistant reply with '## FA check-in — rdar://…' keeps the session in fa."""
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "## FA check-in — rdar://101493937\n\n"
                "### Fail items\n- flash erase incomplete\n"
            ),
        ),
    ]
    mode = resolve_chat_mode(
        "下一步是什么",
        history=history,
        llm=None,
        config=config,
    )
    assert mode == "fa"


def test_history_unbound_header_is_fa(repo_root: Path) -> None:
    """Assistant reply with the unbound FA header keeps the session in fa."""
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "**FA（未绑定 Radar）：** U8600 IIC no output\n"
                "<!-- ee-wiki-scope: iphone/logan/p1 -->"
            ),
        ),
    ]
    mode = resolve_chat_mode(
        "查一下U8600的原理图",
        history=history,
        llm=None,
        config=config,
    )
    assert mode == "fa"


def test_history_non_fa_assistant_does_not_force_fa(repo_root: Path) -> None:
    """A non-FA assistant reply in history must not bind the turn to fa."""
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content="VBAT connects to the PMIC via an LDO.",
        ),
    ]
    mode = resolve_chat_mode(
        "STM32F407 核心参数",
        history=history,
        llm=None,
        config=config,
    )
    assert mode == "wiki"


# ── 4. LLM classify -> fa | wiki ──────────────────────────────────────────


def test_llm_classify_fa_intent_without_radar(repo_root: Path) -> None:
    """Golden sentence: '帮我FA一下为什么U8600…IIC…' with LLM MODE: fa -> fa."""
    config = _config(repo_root)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: fa"
    mode = resolve_chat_mode(
        "帮我FA一下为什么U8600（logan p1）的IIC接口没有输出",
        history=None,
        llm=llm,
        config=config,
    )
    assert mode == "fa"


def test_llm_classify_wiki_for_parameter_query(repo_root: Path) -> None:
    """'STM32F407 核心参数' with LLM MODE: wiki -> wiki."""
    config = _config(repo_root)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: wiki"
    mode = resolve_chat_mode(
        "STM32F407 核心参数",
        history=None,
        llm=llm,
        config=config,
    )
    assert mode == "wiki"


def test_llm_classify_failure_falls_back_to_wiki(repo_root: Path) -> None:
    """When the LLM output is unusable, the conservative default is wiki."""
    config = _config(repo_root)
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "I am not sure what mode this is"
    mode = resolve_chat_mode(
        "帮我查一下U8600的IIC问题",
        history=None,
        llm=llm,
        config=config,
    )
    assert mode == "wiki"


# ── 5. No LLM + no radar + no history -> wiki ─────────────────────────────


def test_no_llm_no_radar_no_history_defaults_wiki(repo_root: Path) -> None:
    config = _config(repo_root)
    mode = resolve_chat_mode(
        "帮我FA一下为什么U8600的IIC接口没有输出",
        history=None,
        llm=None,
        config=config,
    )
    assert mode == "wiki"


# ── 6. fa.enabled=False -> always wiki even with LLM ─────────────────────


def test_fa_disabled_forces_wiki(repo_root: Path) -> None:
    """When fa.enabled is False, the LLM classify path is skipped entirely."""
    from dataclasses import replace

    config = load_config(repo_root=repo_root)
    config = replace(
        config,
        fa=replace(config.fa, enabled=False),
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "MODE: fa"
    mode = resolve_chat_mode(
        "帮我FA一下为什么U8600的IIC接口没有输出",
        history=None,
        llm=llm,
        config=config,
    )
    assert mode == "wiki"
    llm.generate.assert_not_called()
