"""Tests for debug-case index and retrieval lookup."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.knowledge.indexer.case_index import (
    build_case_index,
    load_case_index,
    save_case_index,
)
from ee_wiki.retrieval.case_lookup import lookup_case_chunk_ids, search_cases


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={"fa": "failure_analysis"},
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _fa_chunk(
    *,
    chunk_id: str,
    project: str = "demo",
    build: str = "p1",
    source_file: str = "demo/p1/fa/rma.md",
    case_id: str = "RMA-1",
    symptom: str = "No boot",
    suspected_nets: list[str] | None = None,
    suspected_parts: list[str] | None = None,
    root_cause: str = "Open on U101",
) -> Chunk:
    metadata = Metadata(
        project=project,
        build=build,
        document_type="failure_analysis",
        title="RMA report",
        source_file=source_file,
        case_id=case_id,
        symptom=symptom,
        suspected_nets=suspected_nets or ["NET_VCC"],
        suspected_parts=suspected_parts or ["U101"],
        steps=["Measure VCC"],
        root_cause=root_cause,
        keywords=["NO_BOOT", "U101"],
    )
    return Chunk(
        chunk_id=chunk_id,
        content=f"{symptom}. {root_cause}",
        metadata=metadata,
        citation=Citation(
            source_file=source_file,
            chunk_id=chunk_id,
            excerpt=symptom,
        ),
    )


def test_build_and_save_case_index(tmp_path: Path) -> None:
    chunks = [
        _fa_chunk(chunk_id="c1"),
        _fa_chunk(chunk_id="c2"),  # same source → one case, two chunk ids
        Chunk(
            chunk_id="note1",
            content="unrelated",
            metadata=Metadata(
                project="demo",
                build="p1",
                document_type="engineering_note",
                title="Note",
                source_file="demo/p1/note/x.md",
            ),
            citation=Citation(source_file="demo/p1/note/x.md", chunk_id="note1"),
        ),
    ]
    index = build_case_index(chunks)
    assert len(index.cases) == 1
    case = index.cases[0]
    assert case.case_id == "RMA-1"
    assert set(case.chunk_ids) == {"c1", "c2"}
    assert "NET_VCC" in case.suspected_nets

    saved = save_case_index(chunks, tmp_path)
    loaded = load_case_index(tmp_path)
    assert loaded is not None
    assert loaded.cases[0].case_id == saved.cases[0].case_id


def test_search_cases_by_symptom_and_part(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    index = build_case_index(
        [
            _fa_chunk(chunk_id="c1", case_id="RMA-1", symptom="No boot after ESD"),
            _fa_chunk(
                chunk_id="c2",
                case_id="RMA-2",
                source_file="demo/p1/fa/thermal.md",
                symptom="Thermal runaway",
                suspected_parts=["Q20"],
                root_cause="Short on Q20",
            ),
        ]
    )
    hits = search_cases(index, "no boot U101", layout=layout)
    assert hits
    assert hits[0].case_id == "RMA-1"

    thermal = search_cases(index, "Q20 thermal", layout=layout)
    assert thermal
    assert thermal[0].case_id == "RMA-2"


def test_lookup_case_chunk_ids_respects_scope(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    index = build_case_index(
        [
            _fa_chunk(chunk_id="p1", build="p1"),
            _fa_chunk(
                chunk_id="other",
                project="other",
                build="p1",
                source_file="other/p1/fa/x.md",
                case_id="OTHER-1",
            ),
        ]
    )
    matched = lookup_case_chunk_ids(
        index,
        ["NO", "BOOT", "U101"],
        layout=layout,
        target_project="demo",
        target_build="p1",
        scope_inheritance=True,
    )
    assert "p1" in matched
    assert "other" not in matched
