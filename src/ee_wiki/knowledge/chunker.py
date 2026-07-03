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
HEADING_PATH_SEP = " › "


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


def _build_heading_path(*parts: str) -> str:
    """Join heading labels, skipping empties and consecutive duplicates."""
    cleaned: list[str] = []
    for part in parts:
        text = part.strip()
        if text and (not cleaned or text != cleaned[-1]):
            cleaned.append(text)
    return HEADING_PATH_SEP.join(cleaned)


def _heading_line_text(line: str) -> str:
    match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
    return match.group(1).strip() if match else ""


def _document_h1(content: str) -> str:
    """Return the first level-1 heading text outside fenced code blocks."""
    for _, line_text in _iter_lines_outside_fences(content):
        if re.match(r"^#\s+", line_text):
            return _heading_line_text(line_text)
        if re.match(r"^#{2,}\s+", line_text):
            return ""
    return ""


def _section_heading_text(text: str) -> str:
    """Return the first ``#`` / ``##`` heading text in a section."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(#{1,2})\s+(.+)$", stripped)
        if match:
            return match.group(2).strip()
        break
    return ""


def _section_heading_level(text: str) -> int:
    """Return the markdown level of the first heading in a section."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(#+)\s+", stripped)
        if match:
            return len(match.group(1))
        break
    return 0


def _subsection_heading_text(text: str) -> str:
    """Return the first ``###`` heading text in a section."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^###\s+(.+)$", stripped)
        if match:
            return match.group(1).strip()
    return ""


def _is_title_only_preamble(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    return len(lines) == 1 and bool(re.match(r"^#{1,2}\s+", lines[0].strip()))


def _merge_h3_preamble(
    sections: list[tuple[str, str]],
    config: ChunkingConfig,
) -> list[tuple[str, str]]:
    """Merge a short or title-only h3 preamble into the first child section."""
    if len(sections) < 2 or sections[0][0] != "preamble":
        return sections
    preamble_text = sections[0][1].strip()
    if not preamble_text:
        return sections[1:]
    if _is_title_only_preamble(preamble_text) or len(preamble_text) < config.min_chars:
        first_suffix, first_text = sections[1]
        merged = f"{preamble_text}\n\n{first_text}".strip()
        return [(first_suffix, merged)] + list(sections[2:])
    return sections


def _strip_standalone_hr(text: str) -> str:
    """Remove standalone horizontal-rule lines from prose documents."""
    kept = [line for line in text.splitlines() if line.strip() != "---"]
    return "\n".join(kept).strip()


def chunk_index_text(chunk: Chunk) -> str:
    """Return text used for embedding and BM25 indexing.

    Args:
        chunk: Indexed chunk with optional heading path metadata.

    Returns:
        Heading path prefixed to content when present, otherwise raw content.
    """
    if chunk.heading_path:
        return f"{chunk.heading_path}\n\n{chunk.content}"
    return chunk.content


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
    heading_path_prefix: str,
) -> list[tuple[str, str, str]]:
    """Split one section into chunk-sized pieces.

    Schematic sections with ``###`` children split per sub-heading without
    overlap sliding windows. Long OCR code blocks use zero-overlap windows only.
    """
    if _find_heading_matches(text, _H3_HEADING_PATTERN):
        pieces: list[tuple[str, str, str]] = []
        h3_sections = _merge_h3_preamble(_split_by_h3_subsections(text), config)
        for sub_suffix, sub_text in h3_sections:
            combined = f"{suffix}__{sub_suffix}" if sub_suffix != "body" else suffix
            sub_heading = _subsection_heading_text(sub_text)
            sub_path = (
                _build_heading_path(heading_path_prefix, sub_heading)
                if sub_heading
                else heading_path_prefix
            )
            if len(sub_text) <= config.max_chars:
                pieces.append((combined, sub_text, sub_path))
                continue
            window_config = config
            if schematic:
                window_config = ChunkingConfig(
                    max_chars=config.max_chars,
                    overlap_chars=0,
                    min_chars=config.min_chars,
                    excerpt_chars=config.excerpt_chars,
                )
            for window_suffix, window_text in _split_by_window(sub_text, combined, window_config):
                pieces.append((window_suffix, window_text, sub_path))
        return pieces

    if len(text) <= config.max_chars:
        return [(suffix, text, heading_path_prefix)]

    window_config = config
    if schematic:
        window_config = ChunkingConfig(
            max_chars=config.max_chars,
            overlap_chars=0,
            min_chars=config.min_chars,
            excerpt_chars=config.excerpt_chars,
        )
    return [
        (window_suffix, window_text, heading_path_prefix)
        for window_suffix, window_text in _split_by_window(text, suffix, window_config)
    ]


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
    heading_path: str = "",
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
        heading_path=heading_path,
    )


def _section_heading_path_prefix(
    text: str,
    *,
    doc_h1: str,
    page: int,
    schematic: bool,
) -> str:
    """Build the heading path prefix for a section before h3/window splits."""
    section_heading = _section_heading_text(text)
    if _section_heading_level(text) == 1:
        return section_heading
    if schematic:
        page_label = f"页 {page}" if page else ""
        return _build_heading_path(doc_h1, page_label, section_heading)
    return _build_heading_path(doc_h1, section_heading)


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

    doc_h1 = _document_h1(record.content)
    schematic = record.metadata.document_type == SCHEMATIC_DOCUMENT_TYPE

    if schematic:
        page_sections = _split_schematic_pages(record.content)
        raw_sections: list[tuple[str, str, int]] = []
        for page_suffix, page_text, page_num in page_sections:
            raw_sections.extend(_split_schematic_sections(page_suffix, page_text, page_num))
    else:
        raw_sections = _split_by_headings(record.content)

    raw_sections = _merge_small_sections(raw_sections, config)

    chunks: list[Chunk] = []
    for suffix, text, page in raw_sections:
        if not schematic:
            text = _strip_standalone_hr(text)
        heading_path_prefix = _section_heading_path_prefix(
            text,
            doc_h1=doc_h1,
            page=page,
            schematic=schematic,
        )
        for window_suffix, window_text, heading_path in _split_section_for_chunking(
            text,
            suffix,
            config,
            schematic=schematic,
            heading_path_prefix=heading_path_prefix,
        ):
            if not window_text.strip():
                continue
            chunks.append(
                _build_chunk(
                    record,
                    window_suffix,
                    window_text,
                    page=page,
                    config=config,
                    heading_path=heading_path,
                )
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
