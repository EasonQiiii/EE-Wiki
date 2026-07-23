"""Tests for LLM Radar corpus → fail-item extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.generation.fa_evidence import (
    _parse_checkin_background,
    _parse_fail_items_output,
    extract_checkin_background,
    extract_fail_items_from_radar_corpus,
    generate_log_analysis,
)
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DescriptionItem,
    DiagnosisItem,
    RadarProblem,
)


def test_parse_fail_items_bullets() -> None:
    items = _parse_fail_items_output(
        "FAIL_ITEMS:\n- flash cannot erase fully\n- entering standby during test\n"
    )
    assert items is not None
    assert [i.message for i in items] == [
        "flash cannot erase fully",
        "entering standby during test",
    ]


def test_parse_fail_items_none() -> None:
    assert _parse_fail_items_output("FAIL_ITEMS: none") == []


def test_extract_calls_prompt(repo_root: Path) -> None:
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "FAIL_ITEMS:\n- Scarif flash cannot erase fully\n"
    )
    items = extract_fail_items_from_radar_corpus(
        "## Title\nRuby flash erase\n",
        llm=llm,
        repo_root=repo_root,
    )
    assert items is not None
    assert items[0].message.startswith("Scarif")
    prompt = llm.generate.call_args.args[0]
    assert "Ruby flash erase" in prompt
    assert "FAIL_ITEMS" in prompt


def test_parse_checkin_background_validates_related_files() -> None:
    raw = (
        "BACKGROUND: FQT station, Scarif DUT.\n"
        "TRUE_FAIL_HINT: flash not erased fully\n"
        "FA_NOTES:\n- check foo.log\n- pwr_state set factory first\n"
        "RELATED_FILES:\n- foo.log\n- ghost.log\n"
        "UNRESOLVED: none\n"
    )
    bg = _parse_checkin_background(raw, available_names={"foo.log", "photo.png"})
    assert bg is not None
    assert bg.background == "FQT station, Scarif DUT."
    assert bg.true_fail_hint == "flash not erased fully"
    assert bg.fa_notes == ("check foo.log", "pwr_state set factory first")
    # foo.log exists → related; ghost.log missing → demoted to unresolved.
    assert bg.related_files == ("foo.log",)
    assert bg.unresolved == ("ghost.log",)


def test_related_files_normalize_backticks_and_parenthetical() -> None:
    """LLM wrapping must not demote a real attachment to UNRESOLVED (P1-#3)."""
    from ee_wiki.generation.fa_evidence import (
        _match_related_attachment_name,
        _normalize_attachment_name_token,
    )

    assert _normalize_attachment_name_token("`foo.log`") == "foo.log"
    assert _normalize_attachment_name_token("foo.log (log)") == "foo.log"
    assert _normalize_attachment_name_token("foo.log（日志）") == "foo.log"
    assert _normalize_attachment_name_token('"bar.txt".') == "bar.txt"
    assert _normalize_attachment_name_token("path/to/foo.log") == "foo.log"

    available = {"foo.log", "H9H242500041JJY1A_save_100_NG.log", "photo.png"}
    assert _match_related_attachment_name("`foo.log`", available) == "foo.log"
    assert (
        _match_related_attachment_name("foo.log (log)", available) == "foo.log"
    )
    assert (
        _match_related_attachment_name(
            "H9H242500041JJY1A_save_100_NG.log.", available
        )
        == "H9H242500041JJY1A_save_100_NG.log"
    )
    # Case-insensitive exact.
    assert _match_related_attachment_name("FOO.LOG", available) == "foo.log"
    # Bare "log" must not fuzzy-match every *.log.
    assert _match_related_attachment_name("log", available) is None

    raw = (
        "BACKGROUND: erase.\n"
        "TRUE_FAIL_HINT: erase incomplete\n"
        "FA_NOTES:\n- see the NG log\n"
        "RELATED_FILES:\n"
        "- `foo.log`\n"
        "- H9H242500041JJY1A_save_100_NG.log (log)\n"
        "- missing_only.log\n"
        "UNRESOLVED: none\n"
    )
    bg = _parse_checkin_background(raw, available_names=available)
    assert bg is not None
    assert bg.related_files == (
        "foo.log",
        "H9H242500041JJY1A_save_100_NG.log",
    )
    assert bg.unresolved == ("missing_only.log",)


def test_unresolved_entry_promoted_when_normalized_matches() -> None:
    raw = (
        "BACKGROUND: erase.\n"
        "TRUE_FAIL_HINT: erase incomplete\n"
        "FA_NOTES: none\n"
        "RELATED_FILES: none\n"
        "UNRESOLVED:\n- `foo.log`\n"
    )
    bg = _parse_checkin_background(raw, available_names={"foo.log"})
    assert bg is not None
    assert bg.related_files == ("foo.log",)
    assert bg.unresolved == ()


def test_parse_checkin_background_none_sections() -> None:
    raw = (
        "BACKGROUND: monitoring after fix.\n"
        "TRUE_FAIL_HINT: none\n"
        "FA_NOTES: none\n"
        "RELATED_FILES: none\n"
        "UNRESOLVED: none\n"
    )
    bg = _parse_checkin_background(raw, available_names=set())
    assert bg is not None
    assert bg.true_fail_hint == ""
    assert bg.fa_notes == ()
    assert bg.related_files == ()
    assert bg.unresolved == ()


def test_parse_checkin_background_strips_reasoning() -> None:
    raw = (
        "<think>the ticket is about flash erase</think>\n"
        "BACKGROUND: erase failure.\n"
        "TRUE_FAIL_HINT: erase incomplete\n"
        "FA_NOTES: none\n"
        "RELATED_FILES: none\n"
        "UNRESOLVED: none\n"
    )
    bg = _parse_checkin_background(raw, available_names=set())
    assert bg is not None
    assert bg.background == "erase failure."


def test_parse_checkin_background_unusable_returns_none() -> None:
    assert _parse_checkin_background("no structured fields here", available_names=set()) is None


def test_generate_checkin_ai_summary_uses_narrative_prompt(repo_root: Path) -> None:
    from ee_wiki.generation.fa_evidence import generate_checkin_ai_summary
    from ee_wiki.protocols.flames import FailItem, FailItemsResult, FlamesUnitRef

    problem = RadarProblem(
        radar_id="182787079",
        title="IMU Gyro Average Y out of limit",
        description=(DescriptionItem(text="Drop50 MST fail.", added_by="e"),),
        diagnosis=(
            DiagnosisItem(
                text="Next step: CT scan.",
                added_by="wang.baofu@byd.com",
                entry_type="user",
            ),
        ),
        attachments=(),
    )
    fails = FailItemsResult(
        unit=FlamesUnitRef(unit_id="u", serial=None, radar_id="182787079"),
        records=(),
        fail_items=(FailItem(message="Gyro Y OOL", station="radar"),),
        cached_logs=(),
        source="radar",
        needs_user_input=False,
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "跌落后 IMU 校准 Y 轴超限；bench 已复现；下一步 CT scan。"
    )
    text = generate_checkin_ai_summary(
        problem, fails, llm=llm, repo_root=repo_root
    )
    assert text is not None
    assert "CT scan" in text
    prompt = llm.generate.call_args.args[0]
    assert "Background" in prompt
    assert "FA steps so far" in prompt
    assert "Next step or conclusion" in prompt
    assert "never the word" in prompt
    assert "Gyro Y OOL" in prompt


def test_generate_log_analysis_unit(repo_root: Path) -> None:
    """LLM log interpretation for a numeric / out-of-limit log with no literal
    PASS/FAIL must surface the file type, verbatim metrics, and the explicit
    '未见字面 PASS/FAIL' marker — and never fabricate a pass/fail verdict."""
    problem = RadarProblem(
        radar_id="182787079",
        title="IMU Cal_LPNM gyro_y out of limit",
        description=(),
        diagnosis=(
            DiagnosisItem(
                text="Next step: re-cal.",
                added_by="e",
                entry_type="user",
            ),
        ),
        attachments=(),
    )
    cal_log = (
        "gyro_x_average: 0.012\n"
        "gyro_y_average: -0.042\n"
        "out of limit: gyro_y_average below spec\n"
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "1. 文件类型：IMU 校准输出。\n"
        "2. 关键指标：`gyro_y_average: -0.042`、`out of limit`。\n"
        "3. 未见字面 PASS/FAIL，以下为结构解读：gyro_y 超下界。\n"
    )
    text = generate_log_analysis(
        problem, "Cal_LPNM_1.log", cal_log, llm=llm, repo_root=repo_root
    )
    assert text is not None
    assert "未见字面 PASS/FAIL" in text
    assert "gyro_y_average" in text
    prompt = llm.generate.call_args.args[0]
    # Placeholders were substituted; the real log text and the no-fabricate
    # instruction are present in the prompt.
    assert "{{log_text}}" not in prompt
    assert "gyro_y_average" in prompt
    assert "未见字面 PASS/FAIL" in prompt


def test_extract_checkin_background_end_to_end(repo_root: Path) -> None:
    problem = RadarProblem(
        radar_id="700001",
        title="Ruby flash erase",
        description=(DescriptionItem(text="Scarif FATP erase test.", added_by="e"),),
        diagnosis=(
            DiagnosisItem(
                text="Raw fail log please check `foo.log`.",
                added_by="e",
                entry_type="user",
            ),
        ),
        attachments=(AttachmentMeta(file_name="foo.log", kind="attachment"),),
    )
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = (
        "BACKGROUND: Scarif FATP flash erase.\n"
        "TRUE_FAIL_HINT: flash not erased fully\n"
        "FA_NOTES:\n- check foo.log\n"
        "RELATED_FILES:\n- foo.log\n"
        "UNRESOLVED: none\n"
    )
    bg = extract_checkin_background(problem, llm=llm, repo_root=repo_root)
    assert bg is not None
    assert bg.related_files == ("foo.log",)
    prompt = llm.generate.call_args.args[0]
    assert "700001" in prompt
    assert "foo.log" in prompt  # attachment name included in corpus
    assert "## Briefing" in prompt
