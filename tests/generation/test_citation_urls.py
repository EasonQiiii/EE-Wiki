"""Tests for citation URL building."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.generation.citation_urls import (
    asset_url,
    citation_image_urls,
    parse_markdown_image_refs,
    processed_relative_path,
    resolve_asset_relative_path,
    section_fragment,
    source_document_url,
)
from ee_wiki.retrieval.hybrid.engine import HybridChunk


def test_processed_relative_path_maps_under_processed_dir(app_config) -> None:
    rel = processed_relative_path(
        "data/processed/logan/p1/note/iPadManual.md",
        app_config.processed_dir,
    )
    assert rel == "logan/p1/note/iPadManual.md"


def test_section_fragment_strips_window_suffix() -> None:
    assert section_fragment("iPadManual__get-dut-sn__w01") == "#get-dut-sn"


def test_source_document_url_includes_fragment(app_config) -> None:
    url = source_document_url(
        app_config,
        target_file="data/processed/logan/p1/note/iPadManual.md",
        chunk_id="iPadManual__get-dut-sn",
    )
    assert url.endswith("/v1/sources/logan/p1/note/iPadManual.md#get-dut-sn")


def test_parse_markdown_image_refs() -> None:
    content = "See ![setup](iPadManual.assets/screen.png) and ![x](https://example.com/a.png)"
    assert parse_markdown_image_refs(content) == [
        "iPadManual.assets/screen.png",
        "https://example.com/a.png",
    ]


def test_resolve_asset_relative_path(app_config, tmp_path: Path) -> None:
    from dataclasses import replace

    processed = tmp_path / "processed"
    note_dir = processed / "logan/p1/note"
    assets = note_dir / "iPadManual.assets"
    assets.mkdir(parents=True)
    image = assets / "screen.png"
    image.write_bytes(b"png")
    target = note_dir / "iPadManual.md"
    config = replace(app_config, processed_dir=processed)

    rel = resolve_asset_relative_path(str(target), "iPadManual.assets/screen.png", processed)
    assert rel == "logan/p1/note/iPadManual.assets/screen.png"
    assert asset_url(config, asset_rel=rel).endswith(
        "/v1/assets/logan/p1/note/iPadManual.assets/screen.png"
    )


def test_citation_image_urls_from_chunk_content(app_config, tmp_path: Path) -> None:
    from dataclasses import replace

    processed = tmp_path / "processed"
    note_dir = processed / "logan/p1/note"
    assets = note_dir / "manual.assets"
    assets.mkdir(parents=True)
    (assets / "diag.png").write_bytes(b"png")
    target = note_dir / "manual.md"
    target.write_text("doc", encoding="utf-8")
    config = replace(app_config, processed_dir=processed)

    urls = citation_image_urls(
        config,
        target_file=str(target),
        content="![diag](manual.assets/diag.png)",
    )
    assert len(urls) == 1
    assert urls[0].endswith("/v1/assets/logan/p1/note/manual.assets/diag.png")
