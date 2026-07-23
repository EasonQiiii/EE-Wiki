"""Tests for FaSession state: ensure / restore / bind (fa-session.md).

These tests exercise ``ensure_fa_session`` and ``unbound_header_markdown``
without mocking FaAgent or ToolBus — only the session data structure and
its parse/restore logic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ee_wiki.agents.fa_session import (
    FaSession,
    ensure_fa_session,
    unbound_header_markdown,
)
from ee_wiki.common.config import load_config
from ee_wiki.retrieval.rewrite import ConversationTurn


def _config(repo_root: Path):
    return load_config(repo_root=repo_root)


# ── Fresh unbound session ─────────────────────────────────────────────────


def test_fresh_unbound_session_has_ephemeral_case_id(repo_root: Path) -> None:
    config = _config(repo_root)
    session = ensure_fa_session(
        "帮我FA一下为什么U8600的IIC接口没有输出",
        history=None,
        product="iphone",
        project="logan",
        build="p1",
        config=config,
    )
    assert session.bound is False
    assert session.unbound is True
    assert session.radar_id is None
    assert session.case_id.startswith("fa-unbound-")
    assert session.symptom == "帮我FA一下为什么U8600的IIC接口没有输出"
    assert session.product == "iphone"
    assert session.project == "logan"
    assert session.build == "p1"


def test_fresh_unbound_without_scope(repo_root: Path) -> None:
    config = _config(repo_root)
    session = ensure_fa_session(
        "帮我FA一下U8600 IIC没输出",
        history=None,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is False
    assert session.product is None
    assert session.project is None
    assert session.build is None


# ── Bound session from radar id in question ──────────────────────────────


def test_radar_id_in_question_creates_bound_session(repo_root: Path) -> None:
    config = _config(repo_root)
    session = ensure_fa_session(
        "radar://101493937",
        history=None,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is True
    assert session.radar_id == "101493937"
    assert session.case_id == "101493937"


# ── Restore from history ─────────────────────────────────────────────────


def test_restore_bound_from_history_header(repo_root: Path) -> None:
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "## FA check-in — rdar://42424242\n\n"
                "### Fail items\n- flash erase incomplete\n"
            ),
        ),
    ]
    session = ensure_fa_session(
        "下一步是什么",
        history=history,
        product="iphone",
        project="logan",
        build="p1",
        config=config,
    )
    assert session.bound is True
    assert session.radar_id == "42424242"
    assert session.case_id == "42424242"


def test_restore_unbound_from_history_header(repo_root: Path) -> None:
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
    session = ensure_fa_session(
        "查一下U8600的原理图",
        history=history,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is False
    assert session.radar_id is None
    assert session.symptom == "U8600 IIC no output"
    assert session.product == "iphone"
    assert session.project == "logan"
    assert session.build == "p1"


# ── Bind: unbound session + new radar id ─────────────────────────────────


def test_unbound_session_binds_on_radar_id(repo_root: Path) -> None:
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
    session = ensure_fa_session(
        "radar://101493937",
        history=history,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is True
    assert session.radar_id == "101493937"
    assert session.case_id == "101493937"
    # Scope and symptom carried over from the unbound session.
    assert session.product == "iphone"
    assert session.project == "logan"
    assert session.build == "p1"
    assert "U8600" in (session.symptom or "")


def test_unbound_session_stays_unbound_without_radar(repo_root: Path) -> None:
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
    session = ensure_fa_session(
        "帮我追一下 I2C_SDA 这根 net",
        history=history,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is False
    assert session.radar_id is None


# ── unbound_header_markdown round-trip ───────────────────────────────────


def test_unbound_header_round_trips(repo_root: Path) -> None:
    """unbound_header_markdown output is parseable by ensure_fa_session."""
    config = _config(repo_root)
    session1 = ensure_fa_session(
        "U8600 IIC no output",
        history=None,
        product="iphone",
        project="logan",
        build="p1",
        config=config,
    )
    header = unbound_header_markdown(session1)
    assert "**FA（未绑定 Radar）：**" in header
    assert "U8600 IIC no output" in header
    assert "**EE-Wiki scope:**" not in header

    # Simulate next turn: assistant sent the header, user follows up. Scope
    # travels in the invisible marker, not in the visible header.
    history = [
        ConversationTurn(
            role="assistant",
            content=header + "\n<!-- ee-wiki-scope: iphone/logan/p1 -->",
        )
    ]
    session2 = ensure_fa_session(
        "继续查",
        history=history,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session2.bound is False
    assert session2.product == "iphone"
    assert session2.project == "logan"
    assert session2.build == "p1"
    assert session2.symptom == "U8600 IIC no output"


def test_unbound_header_with_none_scope(repo_root: Path) -> None:
    _ = _config(repo_root)  # verify config loads
    session = FaSession(
        case_id="fa-unbound-test",
        radar_id=None,
        product=None,
        project=None,
        build=None,
        symptom="no scope question",
        bound=False,
    )
    header = unbound_header_markdown(session)
    assert "**FA（未绑定 Radar）：**" in header
    assert "no scope question" in header
    assert "product=none" not in header


def test_fresh_unbound_uses_caller_locked_scope(repo_root: Path) -> None:
    """TurnScope is locked by chat; ensure_fa_session must not re-infer."""
    config = _config(repo_root)
    from ee_wiki.retrieval.scope_from_question import merge_scope_from_question

    q = "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"
    product, project, build = merge_scope_from_question(q, config=config)
    session = ensure_fa_session(
        q,
        history=None,
        product=product,
        project=project,
        build=build,
        config=config,
        ctx=None,
    )
    assert session.project == "logan"
    assert session.build == "p1"
    assert session.product == "ipad"


def test_fresh_unbound_does_not_infer_when_caller_omits_scope(
    repo_root: Path,
) -> None:
    """Without a locked TurnScope, FA session keeps none (no second infer)."""
    config = _config(repo_root)
    session = ensure_fa_session(
        "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace",
        history=None,
        product=None,
        project=None,
        build=None,
        config=config,
        ctx=None,
    )
    assert session.product is None
    assert session.project is None
    assert session.build is None


def test_unbound_followup_uses_caller_lock_over_none_header(
    repo_root: Path,
) -> None:
    """Sticky none/none/none header yields to caller-locked logan p1."""
    config = _config(repo_root)
    from ee_wiki.retrieval.scope_from_question import merge_scope_from_question

    q = "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"
    product, project, build = merge_scope_from_question(q, config=config)
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "**FA（未绑定 Radar）：** DP_TBTSNK1_ML_C_N<1>的完整trace\n"
            ),
        ),
    ]
    session = ensure_fa_session(
        q,
        history=history,
        product=product,
        project=project,
        build=build,
        config=config,
        ctx=None,
    )
    assert session.project == "logan"
    assert session.build == "p1"
    assert session.product == "ipad"


def test_ensure_fa_session_never_calls_scope_inference(repo_root: Path) -> None:
    """TurnScope single-point lock (ADR 0012 §6 / ADR 0013): ensure_fa_session
    must read the caller-locked scope and never perform a second NL inference.

    Patching both inference entry points proves ``ensure_fa_session`` does not
    call them — for the caller-locked path and for header inheritance
    (DialogScope gap-fill).
    """
    config = _config(repo_root)
    question = "logan p1 上 U8600 的 I2C_SCL<1> 完整 trace 到哪些 pin？"

    # (a) Caller-locked scope: must pass through unchanged, no NL re-infer.
    with (
        patch(
            "ee_wiki.retrieval.scope_from_question.merge_scope_from_question"
        ) as m_merge,
        patch("ee_wiki.retrieval.scope_extract.extract_scope_rules") as m_extract,
    ):
        session = ensure_fa_session(
            question,
            history=None,
            product="iphone",
            project="logan",
            build="p1",
            config=config,
        )
        assert m_merge.call_count == 0
        assert m_extract.call_count == 0

    assert session.product == "iphone"
    assert session.project == "logan"
    assert session.build == "p1"

    # (b) DialogScope gap-fill: caller product wins; project/build come from the
    #     prior FA header line. Still must not call NL inference.
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "**FA（未绑定 Radar）：** I2C 没输出\n"
                "<!-- ee-wiki-scope: ipad/m2/p1 -->"
            ),
        ),
    ]
    with (
        patch(
            "ee_wiki.retrieval.scope_from_question.merge_scope_from_question"
        ) as m_merge2,
        patch("ee_wiki.retrieval.scope_extract.extract_scope_rules") as m_extract2,
    ):
        session2 = ensure_fa_session(
            question,
            history=history,
            product="iphone",
            project=None,
            build=None,
            config=config,
        )
        assert m_merge2.call_count == 0
        assert m_extract2.call_count == 0

    assert session2.product == "iphone"  # caller TurnScope wins
    assert session2.project == "m2"  # gap-filled from header
    assert session2.build == "p1"  # gap-filled from header


def test_restore_unbound_from_wiki_marker(repo_root: Path) -> None:
    """Wiki->FA follow-up: the prior assistant reply carries only the hidden
    `<!-- ee-wiki-scope: -->` marker (no FA unbound header). ensure_fa_session
    must recover ipad/logan/p1 from that marker so the FA turn is not unbound
    with none/none/none. Mirrors the real Open WebUI round-trip where
    `conversation_id` is absent and history echoes the prior Wiki answer."""
    config = _config(repo_root)
    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "DP_TBTSNK1_ML_C_N<1> 的 trace 需要 CAD netlist 才能给出权威走线。"
                "<!-- ee-wiki-scope: ipad/logan/p1 -->"
            ),
        ),
    ]
    session = ensure_fa_session(
        "是否有针对该走线的EMI/EMC测试数据或建议？",
        history=history,
        product=None,
        project=None,
        build=None,
        config=config,
    )
    assert session.bound is False
    assert session.product == "ipad"
    assert session.project == "logan"
    assert session.build == "p1"


# ── Bound scope restore from Radar component (Problem 3, Phase 0) ──────────


def test_fa_session_bound_restores_scope_from_radar(repo_root: Path) -> None:
    """A bound follow-up whose history has a check-in header but NO
    `**EE-Wiki scope:**` line and NO `<!-- ee-wiki-scope: -->` marker must
    restore product/project/build from the Radar component via
    `resolve_scope_from_problem` (priority 4, ADR 0012 §6). This is what lets
    bound "建议/追模块" turns run scope-required tools instead of being skipped.

    `ensure_fa_session` must NOT call NL scope inference (ADR 0013) — only the
    deterministic alias mapping `start_fa_checkin` uses. Both inference entry
    points are asserted untouched.
    """
    config = _config(repo_root)
    from unittest.mock import MagicMock

    from ee_wiki.integrations.scope import ScopeResolution

    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "## FA check-in — rdar://182787079\n\n"
                "### Fail items\n- flash erase incomplete\n"
            ),
        ),
    ]

    fake_problem = MagicMock(name="RadarProblem")
    with (
        patch(
            "ee_wiki.integrations.factory.build_radar_backend"
        ) as m_backend,
        patch(
            "ee_wiki.agents.fa_session.resolve_scope_from_problem"
        ) as m_resolve,
        patch(
            "ee_wiki.retrieval.scope_from_question.merge_scope_from_question"
        ) as m_merge,
        patch("ee_wiki.retrieval.scope_extract.extract_scope_rules") as m_extract,
    ):
        m_backend.return_value.get_problem.return_value = fake_problem
        m_resolve.return_value = ScopeResolution(
            product="iphone",
            project="logan",
            build="p1",
            source="component",
            confidence="high",
        )
        session = ensure_fa_session(
            "你有没有额外的建议动作？",
            history=history,
            product=None,
            project=None,
            build=None,
            config=config,
        )
        # Radar backend was consulted to fetch the problem.
        m_backend.return_value.get_problem.assert_called_once_with("182787079")
        # Deterministic alias mapping ran (NOT NL inference).
        m_resolve.assert_called_once()
        assert m_merge.call_count == 0
        assert m_extract.call_count == 0

    assert session.bound is True
    assert session.radar_id == "182787079"
    assert session.product == "iphone"
    assert session.project == "logan"
    assert session.build == "p1"


def test_fa_session_bound_scope_caller_wins_over_radar(repo_root: Path) -> None:
    """Caller TurnScope still wins (priority 1). Even though the Radar
    component resolves to iphone/logan/p1, an explicit caller product must be
    preserved and never overwritten by the Radar restore."""
    config = _config(repo_root)
    from unittest.mock import MagicMock

    from ee_wiki.integrations.scope import ScopeResolution

    history = [
        ConversationTurn(
            role="assistant",
            content=(
                "## FA check-in — rdar://182787079\n\n"
                "### Fail items\n- flash erase incomplete\n"
            ),
        ),
    ]
    fake_problem = MagicMock(name="RadarProblem")
    with (
        patch(
            "ee_wiki.integrations.factory.build_radar_backend"
        ) as m_backend,
        patch(
            "ee_wiki.agents.fa_session.resolve_scope_from_problem"
        ) as m_resolve,
    ):
        m_backend.return_value.get_problem.return_value = fake_problem
        m_resolve.return_value = ScopeResolution(
            product="iphone",
            project="logan",
            build="p1",
            source="component",
            confidence="high",
        )
        session = ensure_fa_session(
            "你有没有额外的建议动作？",
            history=history,
            product="ipad",  # caller locked at chat entry
            project="logan",
            build="p1",
            config=config,
        )
        # Radar backend NOT consulted — all axes already supplied by caller.
        m_backend.return_value.get_problem.assert_not_called()
        m_resolve.assert_not_called()

    assert session.product == "ipad"
    assert session.project == "logan"
    assert session.build == "p1"
