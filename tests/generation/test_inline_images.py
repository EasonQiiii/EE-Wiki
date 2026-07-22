"""Tests for inline citation image block building."""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.generation.citation_urls import _encode_path
from ee_wiki.generation.inline_images import build_image_block


def _asset(url_path: str) -> str:
    """Build a public asset URL the same way the app does (base64url path)."""
    return "http://localhost:8080/v1/assets/" + _encode_path(url_path)


def _citation(idx: int, images: tuple[str, ...] = ()) -> Citation:
    return Citation(
        source_file="data/raw/iphone/logan/p1/sch/board.pdf",
        chunk_id=f"board__p{idx:03d}",
        page=idx,
        excerpt="...",
        url="http://localhost:8080/v1/sources/"
        + _encode_path("iphone/logan/p1/sch/board.md")
        + f"#p{idx:03d}",
        images=images,
    )


def test_collects_images_from_referenced_citations() -> None:
    p1 = _asset("iphone/logan/p1/sch/images/board/board_p1_page.png")
    p2 = _asset("iphone/logan/p1/sch/images/board/board_p2_page.png")
    citations = [
        _citation(1, (p1,)),
        _citation(2, (p2,)),
        _citation(3),
    ]
    block = build_image_block("POWER SWITCH 原理 [1] 以及 [2] 相关。", citations)
    assert p1 in block
    assert p2 in block
    assert "相关截图" in block


def test_returns_empty_when_no_markers() -> None:
    citations = [
        _citation(1, (_asset("img1.png"),)),
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
    a, b, c = _asset("a.png"), _asset("b.png"), _asset("c.png")
    citations = [
        _citation(1, (a, b, c)),
    ]
    block = build_image_block("[1]", citations, max_images=2)
    assert block.count("![") == 2
    assert a in block
    assert b in block
    assert c not in block


def test_deduplicates_images_across_citations() -> None:
    shared = _asset("shared.png")
    unique = _asset("unique.png")
    citations = [
        _citation(1, (shared,)),
        _citation(2, (shared, unique)),
    ]
    block = build_image_block("[1] and [2].", citations)
    assert block.count(shared) == 1
    assert unique in block
