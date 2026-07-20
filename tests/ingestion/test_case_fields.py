"""Tests for failure-analysis / debug-case field extraction."""

from __future__ import annotations

from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.case_fields import (
    enrich_failure_analysis_document,
    extract_case_fields,
    split_frontmatter,
)


def test_split_frontmatter_parses_yaml() -> None:
    content = """---
case_id: RMA-100
symptom: No boot
suspected_nets: [NET_VCC, PWR_EN]
---
# Body

More text.
"""
    fm, body = split_frontmatter(content)
    assert fm["case_id"] == "RMA-100"
    assert "Body" in body
    assert "---" not in body


def test_extract_case_fields_from_frontmatter() -> None:
    content = """---
case_id: RMA-2024-001
symptom: Intermittent brownout
suspected_parts:
  - U101
  - TPS61299
steps:
  - Measure VCC
  - Check EN
root_cause: Open solder on U101 pin 3
citations:
  - demo/p1/sch/power.md
---
# Report

Narrative.
"""
    fields = extract_case_fields(content)
    assert fields.case_id == "RMA-2024-001"
    assert fields.symptom == "Intermittent brownout"
    assert "U101" in fields.suspected_parts
    assert "TPS61299" in fields.suspected_parts
    assert "Measure VCC" in fields.steps
    assert "Open solder" in (fields.root_cause or "")
    assert "demo/p1/sch/power.md" in fields.case_citations
    assert fields.body is not None
    assert fields.body.startswith("# Report")


def test_extract_case_fields_from_headings() -> None:
    content = """# FA Report

## Symptom

No boot after power cycle.

## Suspected Nets

- NET_VCC
- PWR_EN

## Suspected Parts

U101, C10

## Steps

- Scope VCC rail
- Reseat connector

## Root Cause

Cold solder joint on U101.
"""
    fields = extract_case_fields(content)
    assert "No boot" in (fields.symptom or "")
    assert "NET_VCC" in fields.suspected_nets
    assert "U101" in fields.suspected_parts
    assert "Scope VCC rail" in fields.steps
    assert "Cold solder" in (fields.root_cause or "")


def test_enrich_failure_analysis_document_strips_frontmatter() -> None:
    content = """---
case_id: CASE-9
symptom: Overheating
---
# Title

Body text.
"""
    doc = StandardDocument(
        content=content,
        metadata=Metadata(
            product="acme",
            project="demo",
            build="p1",
            document_type="failure_analysis",
            title="Title",
            source_file="data/raw/acme/demo/p1/fa/case-9.md",
        ),
        source_ref="/tmp/case-9.md",
    )
    enriched = enrich_failure_analysis_document(doc)
    assert enriched.metadata.case_id == "CASE-9"
    assert enriched.metadata.symptom == "Overheating"
    assert enriched.content.startswith("# Title")
    assert "---" not in enriched.content


def test_enrich_skips_non_fa_documents() -> None:
    doc = StandardDocument(
        content="## Symptom\n\nNo boot\n",
        metadata=Metadata(
            product="acme",
            project="demo",
            build="p1",
            document_type="sop",
            title="SOP",
            source_file="data/raw/acme/demo/p1/sop/x.md",
        ),
        source_ref="/tmp/x.md",
    )
    assert enrich_failure_analysis_document(doc) is doc
