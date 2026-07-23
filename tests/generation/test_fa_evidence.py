"""Tests for LLM Radar corpus → fail-item extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.generation.fa_evidence import (
    _parse_checkin_background,
    _parse_fail_items_output,
    extract_checkin_background,
    extract_fail_items_from_radar_corpus,
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
