"""Shared test-log error extraction for Flames backends."""

from __future__ import annotations

import re
from pathlib import Path

from ee_wiki.protocols.flames import FailItem

_ERROR_LINE = re.compile(
    r"^\s*(?:ERROR|FAIL|FAILED)\b[:\s-]*(?P<msg>.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# Bullet / numbered lines when the user pastes a plain fail list (no ERROR: prefix).
_LIST_ITEM = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s+(?P<msg>\S.+)$",
    re.MULTILINE,
)


def extract_errors_from_text(text: str) -> list[FailItem]:
    """Extract fail/error items from log text or a pasted bullet list.

    Prefers ``ERROR`` / ``FAIL`` / ``FAILED`` lines. If none match, falls back
    to bullet or numbered list items so Open WebUI paste still works.

    Args:
        text: Raw log or user-pasted fail list.

    Returns:
        Fail items (message + optional line number); no station attached yet.
    """
    items: list[FailItem] = []
    for match in _ERROR_LINE.finditer(text):
        line_start = text.count("\n", 0, match.start()) + 1
        msg = match.group("msg").strip()
        if msg:
            items.append(FailItem(message=msg, line_no=line_start))
    if items:
        return items

    for match in _LIST_ITEM.finditer(text):
        line_start = text.count("\n", 0, match.start()) + 1
        msg = match.group("msg").strip()
        if msg:
            items.append(FailItem(message=msg, line_no=line_start))
    if items:
        return items

    # Single non-empty paragraph treated as one fail item when user pastes one line.
    stripped = text.strip()
    if stripped and "\n" not in stripped and len(stripped) >= 3:
        return [FailItem(message=stripped, line_no=1)]
    return []


def extract_errors_from_path(log_path: Path) -> list[FailItem]:
    """Extract fail items from a cached log file.

    Args:
        log_path: Local log path.

    Returns:
        Fail items from file contents.
    """
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return extract_errors_from_text(text)
