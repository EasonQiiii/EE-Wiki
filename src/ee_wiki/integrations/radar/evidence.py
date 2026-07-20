"""Compose Radar title / description / diagnosis into FA evidence text."""

from __future__ import annotations

import re

from ee_wiki.protocols.radar import DiagnosisItem, RadarProblem

# Structural marker from radarclient history rows — not semantic NLP.
_HISTORY_BLOCK = re.compile(
    r"<Radar History>.*?</Radar History>",
    re.IGNORECASE | re.DOTALL,
)


def is_radar_history_entry(text: str) -> bool:
    """Return whether ``text`` is a Radar system history row (not FA notes)."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("<Radar History>") or stripped.startswith("<Radar History"):
        return True
    # Entire body wrapped as history.
    if _HISTORY_BLOCK.fullmatch(stripped):
        return True
    return False


def user_diagnosis_entries(problem: RadarProblem) -> list[DiagnosisItem]:
    """Return diagnosis entries that look like human FA notes / pasted logs."""
    return [
        item
        for item in problem.diagnosis
        if not is_radar_history_entry(item.text)
        and (item.entry_type != "history")
    ]


def compose_radar_evidence_corpus(problem: RadarProblem) -> str:
    """Build a single text corpus from title, description, and user diagnosis.

    Skips ``<Radar History>`` system rows. Attachment file names are listed
    so the LLM / engineer can see referenced NG logs even before download.

    Args:
        problem: Normalized Radar snapshot.

    Returns:
        Multi-section plain text (may be empty when the problem has no notes).
    """
    sections: list[str] = []
    title = (problem.title or "").strip()
    if title:
        sections.append(f"## Title\n{title}")

    desc_parts = [d.text.strip() for d in problem.description if d.text.strip()]
    if desc_parts:
        sections.append("## Description\n" + "\n\n".join(desc_parts))

    diag_parts = [d.text.strip() for d in user_diagnosis_entries(problem)]
    if diag_parts:
        sections.append("## Diagnosis\n" + "\n\n---\n\n".join(diag_parts))

    att_names = [
        a.file_name.strip()
        for a in problem.attachments
        if a.file_name and a.file_name.strip()
    ]
    if att_names:
        sections.append(
            "## Attachments\n" + "\n".join(f"- {name}" for name in att_names)
        )

    return "\n\n".join(sections).strip()


def radar_has_evidence_corpus(problem: RadarProblem) -> bool:
    """Return whether title/description/user diagnosis contain any text."""
    if (problem.title or "").strip():
        # Title alone is weak; still count as corpus for extraction attempt.
        if problem.description or user_diagnosis_entries(problem):
            return True
        # Title-only tickets still worth one LLM pass.
        return bool(problem.title.strip())
    return bool(problem.description or user_diagnosis_entries(problem))
