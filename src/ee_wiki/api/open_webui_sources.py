"""Map EE-Wiki citations to Open WebUI source payloads."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Citation


def _source_display_name(citation: Citation, index: int) -> str:
    """Return a unique, human-readable label for a citation chip."""
    path = citation.source_file
    for prefix in ("data/raw/", "data/processed/"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
            break
    name = Path(path).name or citation.chunk_id
    return f"[{index}] {name}"


def citations_to_open_webui_sources(citations: list[Citation]) -> list[dict[str, object]]:
    """Convert enriched citations to Open WebUI ``sources`` entries.

    Open WebUI renders plain ``[N]`` markers in assistant text and attaches
    clickable source chips from a parallel ``sources`` array on the message.

    Args:
        citations: Enriched citations aligned with context block numbering.

    Returns:
        Open WebUI-compatible source objects for chat completion responses.
    """
    sources: list[dict[str, object]] = []
    for index, citation in enumerate(citations, start=1):
        name = _source_display_name(citation, index)
        url = citation.url or ""
        excerpt = citation.excerpt or ""
        sources.append(
            {
                "document": [excerpt],
                "metadata": [{"source": url, "name": name}],
                "source": {
                    "name": name,
                    "url": url,
                },
            }
        )
    return sources
