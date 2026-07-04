"""Build a markdown image block from citation images referenced in an answer."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ee_wiki.common.types import Citation

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


def _label_from_url(url: str) -> str:
    """Derive a short human-readable label from an image asset URL."""
    path = PurePosixPath(url.split("?", 1)[0])
    return path.name


def build_image_block(
    answer_text: str,
    citations: list[Citation],
    *,
    max_images: int = 4,
) -> str:
    """Return a markdown image block for citation images referenced in *answer_text*.

    Scans the answer for ``[N]`` markers and collects unique image URLs from
    the corresponding citations.  Returns an empty string when no markers are
    found — images are only appended when the LLM explicitly cites a source.

    Args:
        answer_text: The LLM-generated answer text.
        citations: Enriched citations aligned with context numbering
            (1-indexed, so ``citations[0]`` corresponds to ``[1]``).
        max_images: Maximum number of images to include.

    Returns:
        Markdown string (empty when there are no images).
    """
    if not citations:
        return ""

    referenced_indices = sorted(
        {int(m.group(1)) for m in _CITATION_MARKER_RE.finditer(answer_text)}
    )

    if not referenced_indices:
        return ""

    seen: set[str] = set()
    ordered_urls: list[tuple[str, int]] = []

    for idx in referenced_indices:
        if idx < 1 or idx > len(citations):
            continue
        citation = citations[idx - 1]
        for url in citation.images:
            if url not in seen:
                seen.add(url)
                ordered_urls.append((url, idx))
            if len(ordered_urls) >= max_images:
                break
        if len(ordered_urls) >= max_images:
            break

    if not ordered_urls:
        return ""

    lines = ["\n\n---\n\n**相关截图 / Referenced Diagrams**\n"]
    for url, idx in ordered_urls:
        label = _label_from_url(url)
        lines.append(f"![\\[{idx}\\] {label}]({url})")
    return "\n".join(lines) + "\n"
