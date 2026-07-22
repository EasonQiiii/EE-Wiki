"""Tests for the Scarif stub fixture (radar.log → rdar://101493937)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.integrations.radar.stub import (
    CANONICAL_STUB_RADAR_ID,
    StubRadarBackend,
)


def test_canonical_stub_matches_radar_log_sample() -> None:
    backend = StubRadarBackend()
    problem = backend.get_problem(CANONICAL_STUB_RADAR_ID)

    assert problem.radar_id == "101493937"
    assert problem.title == "Ruby,P0,Scarif flash erase issue"
    assert problem.state == "Verify"
    assert problem.component is not None
    assert problem.component.name == "B5xx HW Build FATP"
    assert problem.component.version == "P0"
    assert problem.component.id == 1457538

    names = [a.file_name for a in problem.attachments]
    assert "H9H242500041JJY1A_save_100_NG.log" in names
    assert "H9H242500041JJY1A_save_500_NG.log" in names
    assert "sensor_flash_test_PASS_with_MLB_1.log" in names
    assert "sensor_flash_test_PASS_with_MLB_2.log" in names

    user_diag = [d for d in problem.diagnosis if d.entry_type == "user"]
    assert any("standby" in d.text.lower() for d in user_diag)
    assert any("pwr_state set factory" in d.text for d in user_diag)
    assert any("40x times" in d.text for d in user_diag)
    assert any("<Radar History>" in d.text for d in problem.diagnosis)


def test_non_canonical_id_reuses_narrative_with_config_component() -> None:
    backend = StubRadarBackend(
        default_component_name="ipad/logan",
        default_component_version="P1",
    )
    problem = backend.get_problem("888001")
    assert problem.title == "Ruby,P0,Scarif flash erase issue"
    assert problem.component is not None
    assert problem.component.name == "ipad/logan"
    assert problem.component.version == "P1"
    assert any(
        a.file_name == "H9H242500041JJY1A_save_100_NG.log"
        for a in problem.attachments
    )


def test_format_diagnosis_steps_quotes_radar_not_true_fail() -> None:
    from ee_wiki.integrations.radar.evidence import format_radar_diagnosis_steps

    problem = StubRadarBackend().get_problem(CANONICAL_STUB_RADAR_ID)
    md = format_radar_diagnosis_steps(problem, include_history=True)
    assert "Radar diagnosis steps" in md
    assert "true-fail" not in md.lower() or "不是" in md
    assert "standby" in md.lower()
    assert "pwr_state set factory" in md
    assert "40x times" in md
    assert "H9H242500041JJY1A_save_100_NG.log" in md


def test_fa_chat_lists_diagnosis_steps_not_hallucinated_true_fail(
    repo_root: Path, tmp_path: Path
) -> None:
    from dataclasses import replace

    from ee_wiki.common.config import load_config
    from ee_wiki.integrations.fa_chat import try_fa_chat_reply
    from ee_wiki.retrieval.rewrite import ConversationTurn

    config = load_config(repo_root=repo_root)
    config = replace(config, cache_dir=tmp_path / "cache")
    history = [
        ConversationTurn(
            role="assistant",
            content="## FA check-in — rdar://101493937\n\n**Title:** Scarif\n",
        )
    ]
    reply = try_fa_chat_reply(
        config, "你可以列出radar里已经完成的FA步骤吗", history
    )
    assert reply is not None
    assert "Radar diagnosis steps" in reply
    assert "pwr_state set factory" in reply
    assert "true-fail" not in reply.lower() or "不是" in reply
    # Must not invent module triage conclusions.
    assert "模块归因" not in reply

