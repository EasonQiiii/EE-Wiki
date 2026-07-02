# 0001. Document Chunking Strategy

Date: 2026-07-01
Status: accepted

## Context

EE-Wiki V1 retrieval operates on **chunks**, not whole processed documents. Poor chunk boundaries dilute embedding signals and cause the reranker (512-token window) to miss relevant content — especially for multi-page schematic PDFs merged into one Markdown file.

Processed documents live under `data/processed/` as one `.md` per raw file. Chunking runs at **index time** so re-indexing does not require re-ingest.

## Decision

### 1. Split by `document_type`

| `document_type` | Primary split | Secondary split |
|-----------------|---------------|-----------------|
| `schematic` | Page boundaries (`\n---\n` from ingest merge) | `##` headings within a page when over `max_chars` |
| All others (note, sop, datasheet, …) | Markdown headings (`#`, `##`) | Character window with overlap when a section exceeds `max_chars` |

### 2. Size limits (config: `chunking.*`)

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `max_chars` | 1500 | Keeps chunks within embedding/reranker sweet spot |
| `overlap_chars` | 100 | Preserves context across window splits |
| `min_chars` | 50 | Merges tiny fragments into the previous chunk |
| `excerpt_chars` | 200 | Citation preview length for API responses |

### 3. Identifiers and provenance

- `chunk_id`: `{doc_stem}__{suffix}` — e.g. `board__p002`, `manual__power-section`, `board__p002__s03`
- Each chunk inherits document metadata (`project`, `build`, `document_type`, `source_file`, `target_file`, …)
- Schematic chunks set `metadata.page` / `citation.page` to the page number
- `citation.excerpt` = first `excerpt_chars` of chunk content

### 4. Pipeline placement

```
data/processed/*.md → chunker → list[Chunk] → indexer → data/indexes/
```

Retrieval loads persisted indexes; it does not re-chunk at query time.

## Consequences

- Schematic Q&A ("VBAT on U0902") can hit a single page chunk instead of a 20-page report.
- Re-index after changing chunk settings without touching `data/raw/`.
- Future V2 may attach page-filtered `major_components` / `nets` per chunk; V1 inherits document-level lists.
- Chunking defaults for schematics vs prose are now explicit; changes require an ADR update.
