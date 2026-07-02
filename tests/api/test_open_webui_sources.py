"""Tests for Open WebUI source mapping."""

from __future__ import annotations

from ee_wiki.api.open_webui_sources import citations_to_open_webui_sources
from ee_wiki.common.types import Citation


def test_citations_to_open_webui_sources_maps_urls_and_excerpts() -> None:
    citations = [
        Citation(
            source_file="data/raw/logan/p1/note/iPadManual.md",
            chunk_id="manual__sysdiagnose",
            page=0,
            excerpt="Run sysdiagnose on the DUT.",
            url="http://localhost:8080/v1/sources/logan/p1/note/iPadManual.md#sysdiagnose",
        ),
        Citation(
            source_file="data/raw/logan/p1/note/iPadManual.md",
            chunk_id="manual__rsync",
            page=0,
            excerpt="rsync logs from the DUT.",
            url="http://localhost:8080/v1/sources/logan/p1/note/iPadManual.md#rsync",
        ),
    ]

    sources = citations_to_open_webui_sources(citations)

    assert len(sources) == 2
    assert sources[0]["source"] == {
        "name": "[1] iPadManual.md",
        "url": citations[0].url,
    }
    assert sources[0]["document"] == ["Run sysdiagnose on the DUT."]
    assert sources[0]["metadata"] == [
        {"source": citations[0].url, "name": "[1] iPadManual.md"}
    ]
    assert sources[1]["source"]["name"] == "[2] iPadManual.md"
