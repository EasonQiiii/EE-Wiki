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
| `schematic` | Page boundaries (`\n---\n` from ingest merge) | `##` headings within a page; `###` sub-sections for module/signal blocks |
| All others (note, sop, datasheet, …) | Markdown headings (`#`, `##`) | Character window with overlap when a section exceeds `max_chars` |

### 2. Size limits (config: `chunking.*`)

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `max_chars` | 1500 | Keeps chunks within embedding/reranker sweet spot |
| `overlap_chars` | 100 | Preserves context across window splits |
| `min_chars` | 50 | Merges tiny fragments into the previous section |
| `excerpt_chars` | 200 | Citation preview length for API responses |

### 3. Identifiers and provenance

- `chunk_id`: `{doc_stem}__{suffix}` — e.g. `board__p002`, `manual__power`, `manual__power__w02`
- Each chunk inherits document metadata (`project`, `build`, `document_type`, `source_file`, `target_file`, …)
- Schematic chunks set `metadata.page` / `citation.page` to the page number
- `citation.excerpt` = first `excerpt_chars` of chunk content

### 4. Pipeline placement

```
data/processed/*.md → chunker → list[Chunk] → indexer → data/indexes/
```

Retrieval loads persisted indexes; it does not re-chunk at query time.

## Amendment (2026-07-02): structure-aware boundaries + section expansion

### Problem

Engineering notes often mix Markdown headings with shell/Python comment lines (`# …`) inside fenced code blocks. Naive heading detection treated those comments as section boundaries, splitting one procedure across multiple chunks (e.g. a “Get DUT SN” section separated from its commands). Retrieval then matched unrelated sections that shared query terms like “get” or “serial”.

A single-chunk-per-file approach avoids fragmentation but hurts recall precision on long documents. Per-document fixes do not scale.

### Additional decisions

#### A. Fence-aware heading detection (index time)

When splitting on `#` / `##` / `###`, **ignore lines inside ` ``` ` fenced code blocks**. Heading splits apply only to document structure, not to comment syntax inside examples.

#### B. Atomic fenced code blocks (index time)

When windowing a long section, treat each fenced block as an indivisible unit. Pack prose and code blocks into chunks up to `max_chars`; never split mid-fence. A code block larger than `max_chars` is stored as one chunk.

Implementation: `src/ee_wiki/knowledge/chunker.py`.

#### C. Section expansion (query time)

Use **small chunks for recall, merged sections for generation**:

1. Hybrid retrieval ranks individual chunks (`top_k_final` hits).
2. When `retrieval.expand_sections: true` (default), each hit is expanded to all chunks sharing the same section key ( `chunk_id` with `__wNN` window suffix stripped).
3. Sibling contents are concatenated in document order into one context block for the LLM.

Config: `retrieval.expand_sections` in `config/default.yaml`.

Implementation: `src/ee_wiki/retrieval/section_expand.py`, wired in `retrieval/hybrid/engine.py`.

Section expansion covers window splits (`__w01`, `__w02`). It does **not** merge chunks that were incorrectly assigned different section slugs — those require chunker fixes and re-index.

### Re-index required

After chunker or section-expansion logic changes:

```bash
python scripts/index.py
```

## Consequences

- Schematic Q&A ("VBAT on U0902") can hit a single page chunk instead of a 20-page report.
- Procedure sections in engineering notes (commands under a `##` heading) stay intact when code uses `#` comments.
- Long sections still split for embedding quality; retrieval reassembles them for generation.
- Re-index after changing chunk settings without touching `data/raw/`.
- Future V2 may attach page-filtered `major_components` / `nets` per chunk; V1 inherits document-level lists.
- Chunking and retrieval context rules are documented in [data-flow.md](../architecture/data-flow.md).
