"""Tests for document chunking."""

from __future__ import annotations

from ee_wiki.common.config import ChunkingConfig
from ee_wiki.common.types import Metadata, PageMetadata
from ee_wiki.knowledge.chunker import chunk_index_text, chunk_processed_record
from ee_wiki.knowledge.loader import ProcessedRecord

_MODULE_A = "DISPLAY&SENSOR"
_NET_A0 = "IFACE_D0"
_NET_A1 = "IFACE_D1"
_PREFIX_A = "IFACE"


def _record(
    *,
    stem: str,
    content: str,
    document_type: str = "engineering_note",
    page: int = 0,
) -> ProcessedRecord:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type=document_type,
        title=stem,
        source_file=f"data/raw/logan/p1/note/{stem}.md",
        target_file=f"data/processed/logan/p1/note/{stem}.md",
        page=page,
    )
    return ProcessedRecord(
        chunk_id=stem,
        content=content,
        metadata=metadata,
        target_file=metadata.target_file,
    )


def test_prose_splits_by_headings() -> None:
    content = "# Title\n\nIntro text.\n\n## Power\n\nVBAT details.\n\n## Debug\n\nUART notes."
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="manual", content=content), config)

    assert len(chunks) == 3
    assert chunks[0].chunk_id == "manual__title"
    assert "Intro text" in chunks[0].content
    assert chunks[1].chunk_id == "manual__power"
    assert "VBAT" in chunks[1].content
    assert chunks[2].chunk_id == "manual__debug"


def test_schematic_splits_by_page_separator() -> None:
    content = (
        "# 电子图纸分析报告：board\n\n"
        "U0902 VBAT on page one\n\n"
        "---\n\n"
        "PMIC GND on page two"
    )
    config = ChunkingConfig()
    record = _record(stem="board", content=content, document_type="schematic")
    chunks = chunk_processed_record(record, config)

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "board__p001"
    assert chunks[0].metadata.page == 1
    assert chunks[0].citation.page == 1
    assert "U0902" in chunks[0].content
    assert chunks[1].chunk_id == "board__p002"
    assert "PMIC" in chunks[1].content


def test_schematic_page_metadata_applied_per_chunk() -> None:
    content = (
        "# 电子图纸分析报告：board\n\n"
        "U101 on page one\n\n"
        "---\n\n"
        "U102 on page two"
    )
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="schematic",
        title="board",
        source_file="data/raw/logan/p1/sch/board.pdf",
        target_file="data/processed/logan/p1/sch/board.md",
        major_components=["U101", "U102"],
        nets=["VBAT", "GND"],
        interfaces=["RMII"],
        pages=[
            PageMetadata(page=1, major_components=["U101"], nets=["VBAT"], interfaces=["RMII"]),
            PageMetadata(page=2, major_components=["U102"], nets=["GND"], interfaces=[]),
        ],
    )
    record = ProcessedRecord(
        chunk_id="board",
        content=content,
        metadata=metadata,
        target_file=metadata.target_file,
    )
    chunks = chunk_processed_record(record, ChunkingConfig())

    assert chunks[0].metadata.major_components == ["U101"]
    assert chunks[0].metadata.nets == ["VBAT"]
    assert chunks[0].metadata.interfaces == ["RMII"]
    assert chunks[1].metadata.major_components == ["U102"]
    assert chunks[1].metadata.nets == ["GND"]
    assert chunks[1].metadata.interfaces == []
    assert chunks[0].metadata.pages is None
    assert chunks[1].metadata.pages is None


def test_long_section_splits_with_overlap() -> None:
    paragraph = "VBAT net connects to U0902. " * 80
    content = f"## Power\n\n{paragraph}"
    config = ChunkingConfig(max_chars=400, overlap_chars=50, min_chars=20)
    chunks = chunk_processed_record(_record(stem="long", content=content), config)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 400 for chunk in chunks)
    assert chunks[0].chunk_id == "long__power"
    assert chunks[1].chunk_id.startswith("long__power__w")


def test_small_fragments_merge_into_previous() -> None:
    content = "## Main\n\nLong enough section content here.\n\norphan ok"
    config = ChunkingConfig(min_chars=30)
    chunks = chunk_processed_record(_record(stem="frag", content=content), config)

    assert len(chunks) == 1
    assert "orphan ok" in chunks[0].content


def test_schematic_signal_section_splits_by_h3_not_overlap() -> None:
    module_block = "\n".join(
        [
            "### 模块分区",
            f"- `{_MODULE_A}`",
            "",
            f"### 模块：{_MODULE_A}",
            "",
            f"- `{_NET_A0}`",
            f"- `{_NET_A1}`",
            "",
            f"### 数据总线（{_PREFIX_A}）",
            "",
            f"- `{_NET_A0}`",
            f"- `{_NET_A1}`",
            "",
            "### 电源",
            "",
            "- `GND`",
            "- `VCC3.3`",
        ]
    )
    content = (
        "# 电子图纸分析报告：board\n\n"
        f"## 本页模块与接口信号\n\n{module_block}\n\n"
        "---\n\n"
        "## 2. Other page\n\nshort"
    )
    config = ChunkingConfig(max_chars=1500, overlap_chars=100)
    record = _record(stem="board", content=content, document_type="schematic")
    chunks = chunk_processed_record(record, config)

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    assert any("模块-display-sensor" in chunk_id for chunk_id in chunk_ids)
    assert not any("__w01" in chunk_id and "电源" in chunk_id for chunk_id in chunk_ids)
    module_chunk = next(chunk for chunk in chunks if "模块-display-sensor" in chunk.chunk_id)
    assert _NET_A0 in module_chunk.content
    assert _MODULE_A in module_chunk.content


def test_citation_excerpt_truncated() -> None:
    content = "## Section\n\n" + ("x" * 300)
    config = ChunkingConfig(excerpt_chars=50)
    chunks = chunk_processed_record(_record(stem="excerpt", content=content), config)

    assert len(chunks[0].citation.excerpt) <= 51
    assert chunks[0].citation.source_file.endswith("excerpt.md")


def test_shell_comments_inside_fence_do_not_split_sections() -> None:
    content = (
        "## Get DUT SN:\n\n"
        "```shell\n"
        "# OS Mode:\n"
        "sysconfig read -k SrNm\n"
        "#or\n"
        "Component\n\n"
        "# Diags Mode:\n"
        "sn\n"
        "syscfg print mlb\n"
        "```\n\n"
        "## Next Section\n\n"
        "Other notes."
    )
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="iPadManual", content=content), config)

    sn_chunks = [chunk for chunk in chunks if chunk.chunk_id == "iPadManual__get-dut-sn"]
    assert len(sn_chunks) == 1
    assert "sysconfig read -k SrNm" in sn_chunks[0].content
    assert "syscfg print mlb" in sn_chunks[0].content
    assert not any("os-mode" in chunk.chunk_id for chunk in chunks)


def test_long_section_keeps_fenced_code_block_intact() -> None:
    prose = "Intro paragraph.\n\n" * 40
    code = (
        "```shell\n"
        "# OS Mode:\n"
        "sysconfig read -k SrNm\n"
        "# Diags Mode:\n"
        "sn\n"
        "```"
    )
    content = f"## Commands\n\n{prose}{code}"
    config = ChunkingConfig(max_chars=400, overlap_chars=50, min_chars=20)
    chunks = chunk_processed_record(_record(stem="manual", content=content), config)

    code_chunks = [chunk for chunk in chunks if "sysconfig read -k SrNm" in chunk.content]
    assert code_chunks
    for chunk in code_chunks:
        assert chunk.content.count("```") >= 2 or "sn" in chunk.content


def test_h3_preamble_merged_into_first_child() -> None:
    content = (
        "# Manual\n\n"
        "## 9. 快速放电方案\n"
        "### 9.1 方案 A（基础）\n\n"
        "diagstool hwmisc --displayPower=1\n\n"
        "### 9.2 方案 B（高强度负载）\n\n"
        "setbright 1.0\n"
    )
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="ipadmanal", content=content), config)

    assert not any(chunk.chunk_id.endswith("__preamble") for chunk in chunks)
    first = next(chunk for chunk in chunks if "9-1-方案-a" in chunk.chunk_id)
    assert "## 9. 快速放电方案" in first.content
    assert "diagstool hwmisc" in first.content


def test_heading_path_records_parent_sections() -> None:
    content = (
        "# iPad 工程操作手册\n\n"
        "## 9. 快速放电方案\n"
        "### 9.1 方案 A（基础）\n\n"
        "diagstool hwmisc --displayPower=1\n\n"
        "### 9.2 方案 B（高强度负载）\n\n"
        "setbright 1.0\n"
    )
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="ipadmanal", content=content), config)

    plan_a = next(chunk for chunk in chunks if "9-1-方案-a" in chunk.chunk_id)
    plan_b = next(chunk for chunk in chunks if "9-2-方案-b" in chunk.chunk_id)
    assert plan_a.heading_path == "iPad 工程操作手册 › 9. 快速放电方案 › 9.1 方案 A（基础）"
    assert plan_b.heading_path == "iPad 工程操作手册 › 9. 快速放电方案 › 9.2 方案 B（高强度负载）"
    assert "## 9. 快速放电方案" in plan_a.content


def test_standalone_hr_stripped_from_note_chunks() -> None:
    content = (
        "## 9. 快速放电方案\n"
        "### 9.2 方案 B（高强度负载）\n\n"
        "setbright 1.0\n\n"
        "---\n"
    )
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="ipadmanal", content=content), config)

    chunk = next(chunk for chunk in chunks if "9-2-方案-b" in chunk.chunk_id)
    assert "---" not in chunk.content
    assert "setbright 1.0" in chunk.content


def test_chunk_index_text_prepends_heading_path() -> None:
    content = "## Power\n\nVBAT details."
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="manual", content=content), config)

    indexed = chunk_index_text(chunks[0])
    assert indexed.startswith("Power\n\n## Power")
    assert chunks[0].content.startswith("## Power")
