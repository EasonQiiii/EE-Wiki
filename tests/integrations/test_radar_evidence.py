"""Tests for Radar title/description/diagnosis evidence composition."""

from __future__ import annotations

from ee_wiki.integrations.radar.evidence import (
    compose_radar_evidence_corpus,
    is_radar_history_entry,
    user_diagnosis_entries,
)
from ee_wiki.protocols.radar import (
    AttachmentMeta,
    DescriptionItem,
    DiagnosisItem,
    RadarProblem,
)


def test_skips_radar_history_rows() -> None:
    assert is_radar_history_entry(
        "<Radar History>\nAssignee was changed.\n</Radar History>"
    )
    assert not is_radar_history_entry(
        "The external flash cannot been erased fully after imu save."
    )


def test_compose_corpus_matches_lab_shape() -> None:
    problem = RadarProblem(
        radar_id="101493937",
        title="Ruby,P0,Scarif flash erase issue",
        description=(
            DescriptionItem(
                text="Summary:\nThis rdar is for the Scarif flash cannot erase fully"
            ),
        ),
        diagnosis=(
            DiagnosisItem(
                text="<Radar History>\nNew information added.\n</Radar History>",
                entry_type="history",
            ),
            DiagnosisItem(
                text=(
                    "The external flash cannot been erased fully after "
                    "`imu -d gyro save xxx`."
                ),
                entry_type="user",
            ),
            DiagnosisItem(
                text="It looks like system is entering standby during test",
                entry_type="user",
            ),
        ),
        attachments=(
            AttachmentMeta(file_name="UNIT_save_100_NG.log"),
            AttachmentMeta(file_name="UNIT_save_500_NG.log"),
        ),
    )
    corpus = compose_radar_evidence_corpus(problem)
    assert "## Title" in corpus
    assert "Scarif flash erase" in corpus
    assert "## Description" in corpus
    assert "cannot erase fully" in corpus
    assert "## Diagnosis" in corpus
    assert "entering standby" in corpus
    assert "New information added" not in corpus
    assert "UNIT_save_100_NG.log" in corpus
    assert len(user_diagnosis_entries(problem)) == 2
