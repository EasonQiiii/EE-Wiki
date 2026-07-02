"""Tests for answer streaming helpers."""

from __future__ import annotations

from ee_wiki.generation.references import iter_stream_chunks


def test_iter_stream_chunks_splits_long_text() -> None:
    text = "abcdefghij"
    chunks = list(iter_stream_chunks(text, max_chars=4))

    assert chunks == ["abcd", "efgh", "ij"]
    assert "".join(chunks) == text
