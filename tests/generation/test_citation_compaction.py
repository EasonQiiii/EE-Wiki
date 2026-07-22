"""Regression tests for citation compaction and [N] marker remapping.

Open WebUI collapses ``sources`` entries that share a URL and renumbers the
``[N]`` chips. If we send one source per retrieved chunk (retrieval often
returns several chunks from the same document) the LLM's dense ``[N]`` markers
desynchronise from the surviving source entries, so clicking ``[2]`` can open
the wrong document. ``compact_citations`` + ``remap_citation_markers`` keep the
answer text and the ``sources`` array 1:1.
"""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.generation.citations import (
    StreamingCitationMarkerRemapper,
    compact_citations,
    remap_citation_markers,
)


def _cite(source_file: str, chunk_id: str = "") -> Citation:
    return Citation(
        source_file=source_file,
        chunk_id=chunk_id,
        page=0,
        excerpt="",
        url="",
        images=(),
    )


def test_compact_collapses_same_document() -> None:
    cites = [
        _cite("data/raw/a/doc.pdf", "doc__p1"),
        _cite("data/raw/a/doc.pdf", "doc__p2"),
        _cite("data/raw/b/other.key", "other__p1"),
        _cite("data/raw/a/doc.pdf", "doc__p3"),
    ]
    compacted, mapping = compact_citations(cites)
    # Two unique documents -> two compact sources, first-appearance order.
    assert [c.source_file for c in compacted] == [
        "data/raw/a/doc.pdf",
        "data/raw/b/other.key",
    ]
    # Dense indices [1,2,4] (doc.pdf) map to compact 1; [3] (other) maps to 2.
    assert mapping == {1: 1, 2: 1, 3: 2, 4: 1}


def test_remap_markers_uses_compact_indices() -> None:
    mapping = {1: 1, 2: 1, 3: 2, 4: 1}
    text = "See doc.pdf [2] and other.key [3]; also doc [4]."
    out = remap_citation_markers(text, mapping)
    assert out == "See doc.pdf [1] and other.key [2]; also doc [1]."
    # Markers outside the map survive untouched.
    assert remap_citation_markers("no cite [9]", mapping) == "no cite [9]"


def test_streaming_remapper_handles_split_marker() -> None:
    mapping = {1: 1, 2: 1, 3: 2, 4: 1}
    remapper = StreamingCitationMarkerRemapper(mapping)
    # A marker straddles two fragments: "[3" then "] rest".
    out1 = remapper.feed("intro [3")
    out2 = remapper.feed("] rest [4] end")
    assert out1 == "intro "
    # Combined "intro [3] rest [4] end" remaps [3]->2, [4]->1.
    assert out2 == "[2] rest [1] end"
    assert remapper.finish() == ""


def test_streaming_remapper_flushes_trailing_marker() -> None:
    mapping = {1: 1}
    remapper = StreamingCitationMarkerRemapper(mapping)
    out = remapper.feed("only [1")
    flushed = remapper.finish()
    assert out == "only "
    # Closing "]" never arrived: the incomplete marker is emitted as-is.
    assert flushed == "[1"
