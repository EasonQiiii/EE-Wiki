"""Tests for FA diagnosis-step intent routing (list / summarize / latest).

Problem 2 fix: "简要总结当前的 FA 步骤" must return a short summary, not the
full verbatim diagnosis. The intent (list / summarize / latest) is decided by
the LLM classifier `classify_diagnosis_intent` (ADR 0013: regex = structural
tokens only); the old `_ABOUT_DIAGNOSIS_STEPS` regex is now just a pre-filter.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ee_wiki.common.config import load_config
from ee_wiki.integrations.fa_chat import _session_dialogue_reply
from ee_wiki.protocols.radar import DescriptionItem, DiagnosisItem, RadarProblem


def _fake_problem(radar_id: str = "42424242") -> RadarProblem:
    return RadarProblem(
        radar_id=radar_id,
        title="Scarif flash erase issue",
        state="Verify",
        substate="",
        description=(DescriptionItem(text="Flash erase incomplete on unit X."),),
        diagnosis=(
            DiagnosisItem(
                text="First we swapped the cap and re-ran the test.",
                added_by="alice",
                entry_type="user",
            ),
            DiagnosisItem(
                text="Then measured VDD_CORE and found it dips below spec.",
                added_by="bob",
                entry_type="user",
            ),
            DiagnosisItem(
                text="<Radar History> auto state change </Radar History>",
                added_by="system",
                entry_type="history",
            ),
        ),
        attachments=(),
    )


def _fake_llm(*generate_values: str) -> MagicMock:
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.side_effect = list(generate_values)
    return llm


def _reply(
    config,
    question: str,
    llm,
    problem: RadarProblem,
    radar_id: str = "42424242",
) -> str | None:
    backend = MagicMock()
    backend.get_problem.return_value = problem
    checkin_md = f"## FA check-in — rdar://{radar_id}\n\n"
    with patch(
        "ee_wiki.integrations.factory.build_radar_backend",
        return_value=backend,
    ):
        return _session_dialogue_reply(
            config,
            question,
            radar_id=radar_id,
            checkin_markdown=checkin_md,
            llm=llm,
            cancel_event=None,
        )


def test_summarize_steps_returns_summary_not_verbatim(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    problem = _fake_problem()
    # classify_diagnosis_intent -> summarize_steps; summarizer -> summary text
    llm = _fake_llm(
        "KIND: summarize_steps",
        "**已完成 (Done):**\n- swapped cap and re-ran\n\n"
        "**待做 (Open):**\n- measure VDD_CORE again",
    )
    out = _reply(config, "简要总结当前的FA步骤", llm, problem)
    assert out is not None
    assert "已完成" in out
    assert "待做" in out
    # Must NOT be the verbatim list.
    assert "### Radar diagnosis steps" not in out
    # History system row must not be echoed verbatim.
    assert "auto state change" not in out


def test_list_steps_returns_verbatim(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    problem = _fake_problem()
    llm = _fake_llm("KIND: list_steps")
    out = _reply(config, "列出所有FA步骤", llm, problem)
    assert out is not None
    assert "### Radar diagnosis steps" in out
    assert "First we swapped the cap" in out
    assert "Then measured VDD_CORE" in out


def test_latest_action_returns_only_newest(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    problem = _fake_problem()
    llm = _fake_llm("KIND: latest_action")
    out = _reply(config, "最新一步做了什么", llm, problem)
    assert out is not None
    assert "最新一条 diagnosis" in out
    assert "measured VDD_CORE" in out
    assert "First we swapped the cap" not in out


def test_unrecognized_intent_tries_summary_not_full_dump(repo_root: Path) -> None:
    """Bad KIND parse (None) must try brief summary first — not dump the
    full verbatim list (Problem 2 regression when Qwen wraps KIND badly)."""
    config = load_config(repo_root=repo_root)
    problem = _fake_problem()
    # First generate = classify (unrecognized); second = summarize body.
    llm = _fake_llm("KIND: ???", "短摘要：已换电容，再测 VDD_CORE 偏低。")
    out = _reply(config, "简要总结FA步骤", llm, problem)
    assert out is not None
    assert "短摘要" in out
    assert "### Radar diagnosis steps" not in out


def test_no_llm_stays_fa_bound_without_crash(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    problem = _fake_problem()
    out = _reply(config, "简要总结当前的FA步骤", None, problem)
    assert out is not None
    assert "## FA check-in — rdar://42424242" in out


def test_classify_diagnosis_intent_parser(repo_root: Path) -> None:
    from ee_wiki.generation.classify import classify_diagnosis_intent

    cases = {
        "简要总结当前的FA步骤": "summarize_steps",
        "列出所有FA步骤": "list_steps",
        "最新一步做了什么": "latest_action",
        "FA步骤进展": "other",
    }
    for question, expected in cases.items():
        llm = _fake_llm(f"KIND: {expected}")
        kind = classify_diagnosis_intent(
            question, llm=llm, repo_root=repo_root
        )
        assert kind == expected, question
