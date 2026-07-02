"""Split processed documents into retrieval-sized chunks."""

from __future__ import annotations

import re
from dataclasses import replace

from ee_wiki.common.config import ChunkingConfig
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import Chunk, Citation, Metadata
from ee_wiki.knowledge.loader import ProcessedRecord

_HEADING_PATTERN = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)
_H3_HEADING_PATTERN = re.compile(r"^###\s+(.+)$", re.MULTILINE)
_SLUG_PATTERN = re.compile(r"[^\w\-]+")


def _iter_lines_outside_fences(content: str):
    """Yield ``(line_start, line_text)`` for lines not inside fenced code blocks."""
    in_fence = False
    offset = 0
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            yield offset, line.rstrip("\r\n")
        offset += len(line)


def _find_heading_matches(content: str, pattern: re.Pattern[str]) -> list[_MatchAt]:
    """Find heading regex matches only on lines outside fenced code blocks."""
    matches: list[_MatchAt] = []
    for line_start, line_text in _iter_lines_outside_fences(content):
        match = pattern.match(line_text)
        if match:
            matches.append(_MatchAt(match, line_start))
    return matches


class _MatchAt:
    """Wrap a regex match with an absolute start offset in the parent document."""

    def __init__(self, match: re.Match[str], start: int) -> None:
        self._match = match
        self._start = start

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._start + self._match.end()

    def group(self, index: int = 0) -> str:
        return self._match.group(index)


def _slugify_heading(text: str, *, fallback: str) -> str:
    slug = _SLUG_PATTERN.sub("-", text.strip().lower()).strip("-")
    return slug or fallback


def _excerpt(content: str, max_chars: int) -> str:
    text = content.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _split_into_atomic_blocks(text: str) -> list[str]:
    """Split text into prose spans and intact fenced code blocks."""
    fence_pattern = re.compile(r"(^```[\s\S]*?^```\n?)", re.MULTILINE)
    blocks: list[str] = []
    last = 0
    for match in fence_pattern.finditer(text):
        if match.start() > last:
            prose = text[last : match.start()]
            if prose.strip():
                blocks.append(prose)
        blocks.append(match.group(0))
        last = match.end()
    if last < len(text):
        tail = text[last:]
        if tail.strip():
            blocks.append(tail)
    return blocks if blocks else ([text] if text.strip() else [])


def _split_prose_window(
    text: str,
    base_suffix: str,
    config: ChunkingConfig,
) -> list[tuple[str, str]]:
    """Split prose with paragraph-aware windows and overlap."""
    sections: list[tuple[str, str]] = []
    start = 0
    part = 0
    while start < len(text):
        end = min(start + config.max_chars, len(text))
        if end < len(text):
            paragraph_break = text.rfind("\n\n", start, end)
            if paragraph_break > start + config.min_chars:
                end = paragraph_break
        piece = text[start:end].strip()
        if piece:
            suffix = base_suffix if part == 0 else f"{base_suffix}__w{part:02d}"
            sections.append((suffix, piece))
        if end >= len(text):
            break
        start = max(end - config.overlap_chars, start + 1)
        part += 1
    return sections


def _split_by_window(
    text: str,
    base_suffix: str,
    config: ChunkingConfig,
) -> list[tuple[str, str]]:
    """Split long text with paragraph-aware windows and overlap.

    Fenced code blocks are kept intact; only prose spans are windowed.
    """
    if len(text) <= config.max_chars:
        return [(base_suffix, text)]

    blocks = _split_into_atomic_blocks(text)
    if len(blocks) == 1:
        return _split_prose_window(text, base_suffix, config)

    packed: list[tuple[str, str]] = []
    current = ""
    part = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) > config.max_chars:
            if current.strip():
                suffix = base_suffix if part == 0 else f"{base_suffix}__w{part:02d}"
                packed.extend(_split_prose_window(current.strip(), suffix, config))
                part += 1
                current = ""
            oversized_suffix = base_suffix if part == 0 else f"{base_suffix}__w{part:02d}"
            packed.append((oversized_suffix, block))
            part += 1
            continue
        candidate = f"{current}\n\n{block}".strip() if current else block
        if current and len(candidate) > config.max_chars:
            suffix = base_suffix if part == 0 else f"{base_suffix}__w{part:02d}"
            packed.append((suffix, current.strip()))
            part += 1
            current = block
        else:
            current = candidate
    if current.strip():
        suffix = base_suffix if part == 0 else f"{base_suffix}__w{part:02d}"
        packed.append((suffix, current.strip()))
    return packed if packed else _split_prose_window(text, base_suffix, config)


def _split_by_h3_subsections(text: str) -> list[tuple[str, str]]:
    """Split a section on ``###`` sub-headings outside fenced code blocks."""
    matches = _find_heading_matches(text, _H3_HEADING_PATTERN)
    if not matches:
        return [("body", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("preamble", preamble))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if not section_text:
            continue
        heading = match.group(1).strip()
        suffix = _slugify_heading(heading, fallback=f"h3-{index + 1:02d}")
        sections.append((suffix, section_text))
    return sections


def _split_section_for_chunking(
    text: str,
    suffix: str,
    config: ChunkingConfig,
    *,
    schematic: bool,
) -> list[tuple[str, str]]:
    """Split one section into chunk-sized pieces.

    Schematic sections with ``###`` children split per sub-heading without
    overlap sliding windows. Long OCR code blocks use zero-overlap windows only.
    """
    if _find_heading_matches(text, _H3_HEADING_PATTERN):
        pieces: list[tuple[str, str]] = []
        for sub_suffix, sub_text in _split_by_h3_subsections(text):
            combined = f"{suffix}__{sub_suffix}" if sub_suffix != "body" else suffix
            if len(sub_text) <= config.max_chars:
                pieces.append((combined, sub_text))
                continue
            window_config = config
            if schematic:
                window_config = ChunkingConfig(
                    max_chars=config.max_chars,
                    overlap_chars=0,
                    min_chars=config.min_chars,
                    excerpt_chars=config.excerpt_chars,
                )
            pieces.extend(_split_by_window(sub_text, combined, window_config))
        return pieces

    if len(text) <= config.max_chars:
        return [(suffix, text)]

    window_config = config
    if schematic:
        window_config = ChunkingConfig(
            max_chars=config.max_chars,
            overlap_chars=0,
            min_chars=config.min_chars,
            excerpt_chars=config.excerpt_chars,
        )
    return _split_by_window(text, suffix, window_config)


def _split_by_headings(content: str) -> list[tuple[str, str, int]]:
    """Split prose Markdown on ``#`` / ``##`` headings outside fenced code blocks."""
    matches = _find_heading_matches(content, _HEADING_PATTERN)
    if not matches:
        body = content.strip()
        return [("body", body, 0)] if body else []

    sections: list[tuple[str, str, int]] = []
    if matches[0].start() > 0:
        preamble = content[: matches[0].start()].strip()
        if preamble:
            sections.append(("preamble", preamble, 0))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section_text = content[start:end].strip()
        if not section_text:
            continue
        heading = match.group(2).strip()
        suffix = _slugify_heading(heading, fallback=f"s{index + 1:02d}")
        sections.append((suffix, section_text, 0))
    return sections


def _split_schematic_pages(content: str) -> list[tuple[str, str, int]]:
    """Split schematic reports on ingest page separators."""
    parts = [
        part.strip()
        for part in re.split(r"\n\s*---\s*\n", content)
        if part.strip()
    ]
    if not parts:
        return []
    return [(f"p{index + 1:03d}", part, index + 1) for index, part in enumerate(parts)]


def _split_schematic_sections(
    page_suffix: str,
    page_text: str,
    page_num: int,
) -> list[tuple[str, str, int]]:
    """Further split a schematic page on ``##`` sub-headings."""
    matches = list(re.finditer(r"^##\s+(.+)$", page_text, re.MULTILINE))
    if not matches:
        return [(page_suffix, page_text, page_num)]

    sections: list[tuple[str, str, int]] = []
    if matches[0].start() > 0:
        preamble = page_text[: matches[0].start()].strip()
        if preamble:
            sections.append((page_suffix, preamble, page_num))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        section_text = page_text[start:end].strip()
        if not section_text:
            continue
        heading = match.group(1).strip()
        sub_suffix = _slugify_heading(heading, fallback=f"s{index + 1:02d}")
        sections.append((f"{page_suffix}__{sub_suffix}", section_text, page_num))
    return sections


def _merge_small_sections(
    sections: list[tuple[str, str, int]],
    config: ChunkingConfig,
) -> list[tuple[str, str, int]]:
    """Merge tiny non-heading fragments shorter than ``min_chars``."""

    def _keep_separate(text: str) -> bool:
        if len(text) >= config.min_chars:
            return True
        return bool(_HEADING_PATTERN.search(text))

    if not sections:
        return []

    merged: list[tuple[str, str, int]] = []
    for suffix, text, page in sections:
        if merged and not _keep_separate(text) and merged[-1][2] == page:
            prev_suffix, prev_text, prev_page = merged[-1]
            merged[-1] = (prev_suffix, f"{prev_text}\n\n{text}".strip(), prev_page)
        else:
            merged.append((suffix, text, page))
    return merged


def _build_chunk(
    record: ProcessedRecord,
    suffix: str,
    content: str,
    *,
    page: int,
    config: ChunkingConfig,
) -> Chunk:
    chunk_id = f"{record.chunk_id}__{suffix}"
    metadata: Metadata = replace(record.metadata, page=page) if page else record.metadata
    excerpt = _excerpt(content, config.excerpt_chars)
    citation = Citation(
        source_file=metadata.source_file,
        chunk_id=chunk_id,
        page=page,
        excerpt=excerpt,
    )
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        metadata=metadata,
        citation=citation,
    )


def chunk_processed_record(
    record: ProcessedRecord,
    config: ChunkingConfig,
) -> list[Chunk]:
    """Split one processed document into retrieval chunks.

    Schematic documents split by page (``\\n---\\n``) then ``##`` sections.
    Other document types split by ``#`` / ``##`` headings. Sections longer
    than ``max_chars`` are windowed with overlap.

    Args:
        record: Loaded processed document.
        config: Chunk size and overlap settings.

    Returns:
        Ordered list of :class:`Chunk` instances with citations attached.
    """
    if not record.content.strip():
        return []

    if record.metadata.document_type == SCHEMATIC_DOCUMENT_TYPE:
        page_sections = _split_schematic_pages(record.content)
        raw_sections: list[tuple[str, str, int]] = []
        for page_suffix, page_text, page_num in page_sections:
            raw_sections.extend(_split_schematic_sections(page_suffix, page_text, page_num))
    else:
        raw_sections = _split_by_headings(record.content)

    raw_sections = _merge_small_sections(raw_sections, config)

    chunks: list[Chunk] = []
    schematic = record.metadata.document_type == SCHEMATIC_DOCUMENT_TYPE
    for suffix, text, page in raw_sections:
        for window_suffix, window_text in _split_section_for_chunking(
            text,
            suffix,
            config,
            schematic=schematic,
        ):
            if not window_text.strip():
                continue
            chunks.append(
                _build_chunk(record, window_suffix, window_text, page=page, config=config)
            )
    return chunks


def chunk_processed_records(
    records: list[ProcessedRecord],
    config: ChunkingConfig,
) -> list[Chunk]:
    """Chunk multiple processed documents.

    Args:
        records: Loaded processed documents.
        config: Chunk size and overlap settings.

    Returns:
        Flat list of chunks in document scan order.
    """
    chunks: list[Chunk] = []
    for record in records:
        chunks.extend(chunk_processed_record(record, config))
    return chunks
