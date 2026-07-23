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


def format_radar_diagnosis_steps(
    problem: RadarProblem,
    *,
    include_history: bool = False,
    preview_chars: int = 900,
) -> str:
    """Format Radar diagnosis as a numbered FA step list (source of truth).

    Args:
        problem: Normalized Radar snapshot.
        include_history: When true, append a short Radar History footnote.
        preview_chars: Max characters per user diagnosis step body.

    Returns:
        Markdown listing diagnosis steps; empty string when none.
    """
    rid = problem.radar_id
    user_steps = user_diagnosis_entries(problem)
    lines: list[str] = [
        f"## FA check-in — rdar://{rid}",
        "",
        f"**Title:** {problem.title or '—'}",
        f"**State:** {problem.state or '—'} / {problem.substate or '—'}",
        "",
        "### Radar diagnosis steps（原文，非 EE-Wiki 推断）",
        "",
    ]
    if not user_steps:
        lines.append("_No user diagnosis notes on this Radar yet._")
    else:
        lines.append(
            "以下按时间顺序列出该 Radar 上的 **人工 diagnosis**（已跳过 "
            "`<Radar History>` 系统行）。**不是** true-fail / 根因结论。"
        )
        lines.append("")
        for i, item in enumerate(user_steps, start=1):
            who = (item.added_by or "—").strip()
            body = item.text.strip()
            if len(body) > preview_chars:
                body = body[: preview_chars - 1].rstrip() + "…"
            lines.append(f"**{i}. {who}**")
            lines.append("")
            lines.append(body)
            lines.append("")

    if include_history:
        hist = [
            d
            for d in problem.diagnosis
            if is_radar_history_entry(d.text) or d.entry_type == "history"
        ]
        if hist:
            lines.append("### Radar History（系统行，摘要）")
            lines.append("")
            for d in hist[-6:]:
                snippet = _HISTORY_BLOCK.sub("", d.text).strip() or d.text.strip()
                snippet = re.sub(r"\s+", " ", snippet)
                if len(snippet) > 160:
                    snippet = snippet[:157] + "…"
                lines.append(f"- {snippet}")

    return "\n".join(lines).rstrip() + "\n"


def diagnosis_steps_text(
    problem: RadarProblem,
    *,
    preview_chars: int = 1200,
) -> str:
    """Return raw numbered diagnosis text (no markdown header / History).

    Used to feed the LLM summarizer. Each line is ``N. [who] body``. Empty
    string when there are no human diagnosis entries.
    """
    entries = user_diagnosis_entries(problem)
    if not entries:
        return ""
    lines: list[str] = []
    for i, item in enumerate(entries, start=1):
        who = (item.added_by or "—").strip()
        body = item.text.strip()
        if len(body) > preview_chars:
            body = body[: preview_chars - 1].rstrip() + "…"
        lines.append(f"{i}. [{who}] {body}")
    return "\n".join(lines)


def format_latest_diagnosis_action(problem: RadarProblem) -> str:
    """Return only the most recent human diagnosis entry (source of truth).

    Used when the user asks for the latest / most recent FA step. Reuses
    ``user_diagnosis_entries`` so ordering and history filtering stay in one
    place.
    """
    rid = problem.radar_id
    entries = user_diagnosis_entries(problem)
    if not entries:
        return (
            f"## FA check-in — rdar://{rid}\n\n"
            "_No user diagnosis notes on this Radar yet._"
        )
    item = entries[-1]
    who = (item.added_by or "—").strip()
    body = item.text.strip()
    return (
        f"## FA check-in — rdar://{rid}\n\n"
        f"**最新一条 diagnosis（{who}）：**\n\n{body}"
    )


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
