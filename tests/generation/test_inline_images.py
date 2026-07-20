"""Tests for inline citation image block building."""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.generation.inline_images import build_image_block


def _citation(idx: int, images: tuple[str, ...] = ()) -> Citation:
    return Citation(
        source_file="data/raw/iphone/logan/p1/sch/board.pdf",
        chunk_id=f"board__p{idx:03d}",
        page=idx,
        excerpt="...",
        url=f"http://localhost:8080/v1/sources/iphone/logan/p1/sch/board.md#p{idx:03d}",
        images=images,
    )


def test_collects_images_from_referenced_citations() -> None:
    citations = [
        _citation(1, ("http://localhost:8080/v1/assets/iphone/logan/p1/sch/images/board/board_p1_page.png",)),
        _citation(2, ("http://localhost:8080/v1/assets/iphone/logan/p1/sch/images/board/board_p2_page.png",)),
        _citation(3),
    ]
    block = build_image_block("POWER SWITCH 原理 [1] 以及 [2] 相关。", citations)
    assert "board_p1_page.png" in block
    assert "board_p2_page.png" in block
    assert "相关截图" in block


def test_returns_empty_when_no_markers() -> None:
    citations = [
        _citation(1, ("http://localhost:8080/v1/assets/img1.png",)),
        _citation(2),
    ]
    block = build_image_block("No citation markers here.", citations)
    assert block == ""


def test_returns_empty_when_no_images() -> None:
    citations = [_citation(1), _citation(2)]
    block = build_image_block("Answer [1] [2].", citations)
    assert block == ""


def test_returns_empty_when_no_citations() -> None:
    assert build_image_block("Answer text.", []) == ""


def test_respects_max_images() -> None:
    citations = [
        _citation(1, (
            "http://localhost:8080/v1/assets/a.png",
            "http://localhost:8080/v1/assets/b.png",
            "http://localhost:8080/v1/assets/c.png",
        )),
    ]
    block = build_image_block("[1]", citations, max_images=2)
    assert block.count("![") == 2
    assert "a.png" in block
    assert "b.png" in block
    assert "c.png" not in block


def test_deduplicates_images_across_citations() -> None:
    shared = "http://localhost:8080/v1/assets/shared.png"
    citations = [
        _citation(1, (shared,)),
        _citation(2, (shared, "http://localhost:8080/v1/assets/unique.png")),
    ]
    block = build_image_block("[1] and [2].", citations)
    assert block.count(shared) == 1
    assert "unique.png" in block
