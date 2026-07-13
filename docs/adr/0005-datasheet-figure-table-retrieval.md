# 0005. Datasheet Figure/Table Retrieval

Date: 2026-07-11  
Status: accepted (partial — retrieval + ingest hooks + VLM quality gate; re-ingest required for full benefit)

## Context

STM32F407 datasheet queries exposed systematic RAG failures (2026-07-11):

| Query | Expected | Observed failure |
|-------|----------|------------------|
| `Figure 58` 描述什么？ | Figure 58 = synchronous **non-multiplexed** NOR/PSRAM read timings (PDF page 134) | Top hit was **PDF page 58** pin tables (`## Page 58`) |
| `Synchronous non-multiplexed NOR/PSRAM read timings` | Page 134 timing table (`FSMC_D[15:0]`, Table 77) | Top hit was **multiplexed** page 131; LLM extrapolated wrong bus params |

Root causes:

1. **Figure N ≠ Page N** — chunk headings use `## Page N`; Figure numbers appear only in TOC or OCR appendix unless enriched.
2. **Near-duplicate section titles** — `multiplexed` vs `non-multiplexed` differ by one token; hybrid ranker did not penalize the wrong variant.
3. **VLM extraction gaps** — some graph/table pages (e.g. page 131) produce corrupted markdown; OCR fidelity appendix holds correct Figure/Table labels but ranked low.

## Decision

Implement a phased fix (code in `src/ee_wiki/`):

### Implemented (2026-07-11)

1. **Ingest** — `datasheet_pdf/labels.py`: parse OCR text layer for `Figure N` / `Table N` + title; prepend `###` headings to VLM markdown in `merge_pages()` when missing.
2. **Chunk keywords** — `chunker._extract_datasheet_chunk_labels()`: copy Figure/Table labels from chunk content + heading_path into per-chunk `metadata.keywords` (datasheet docs only).
3. **Retrieval** — `retrieval/datasheet_query.py`:
   - Parse `Figure N` / `Table N` / explicit `Page N` from queries.
   - Boost chunks containing the requested Figure/Table label.
   - Penalize `## Page N` / `page-N` chunks when the user asked for **Figure N** (not Page N).
   - Penalize `multiplexed` chunks when the query requires `non-multiplexed` (and similar negated modifiers).
4. **Query expansion** — `expand_hw_query()` appends explicit Figure/Table tokens for BM25/dense recall.
5. **Eval** — golden cases Q-027 (Figure 58) and Q-028 (non-multiplexed timings) in `docs/eval/qa.yaml`.
6. **Ingest quality gate** — `datasheet_pdf/quality.py`: score VLM markdown (empty-cell ratio, length vs OCR, garble, table rows vs OCR lines); on failure for table/graph/mixed pages prefer OCR as the page body before merge/label enrich.

### Mid-term backlog (do not forget)

Captured from production debugging session ([agent transcript](41b94d1f-1701-4091-90a5-c1d861e3c1e7)):

- Ingest时把 Figure N / Table N 写进 chunk 标题或 keywords — **partially done** (OCR enrich + chunk keywords); re-run `scripts/sync.py --force` on datasheets to materialize.
- 检索对 `Figure \d+` 做专门解析，避免和 Page N 混淆 — **done** (`datasheet_query.py`).
- 对 `non-multiplexed` 等否定修饰词做 metadata/BM25 加权 — **done** (rank adjustment in `datasheet_query.py`).
- 修复 page 131 等损坏的 VLM 提取，或优先用 OCR fidelity 表 — **done** (`datasheet_pdf/quality.py`): quality gate on table/graph/mixed pages; when empty-cell / length / garble / row-count heuristics fail and OCR is richer, page body uses OCR (labels still enriched in `merge_pages`). Config: `ingestion.datasheet_pdf.vlm_quality_gate` and related thresholds.

### Re-ingest checklist

After merging this ADR:

```bash
# Scope by path under data/raw/ (sync.py has no --project / --document-type flags)
python3 scripts/sync.py --force data/raw/global/datasheet

# Or ingest + index separately:
python3 scripts/ingest.py --force data/raw/global/datasheet
python3 scripts/index.py --force

python3 scripts/eval_rag.py --mode retrieval --case Q-027 --case Q-028
```

## Consequences

- **Positive**: Figure/Table and negated-modifier queries rank correctly without schema changes; eval cases guard regressions; corrupted VLM table/graph pages fall back to OCR body at ingest.
- **Re-ingest**: Existing processed markdown keeps old headings / VLM bodies until datasheet force sync; retrieval adjustments work immediately on current index; quality-gate OCR body replacement requires re-ingest.
- **Open**: none for backlog item 4 (VLM quality gate + OCR table fallback).
