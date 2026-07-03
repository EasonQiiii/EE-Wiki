# Data Flow

High-level pipeline for EE-Wiki V1. Core types: `src/ee_wiki/common/types.py`.

## Ingestion (write path)

```
Raw file under data/raw/{project}/{build}/{type}/…
    → path parser (derive project, build, document_type)
    → ingestion/parsers/*
    → StandardDocument (Markdown + Metadata)
    → knowledge/store → data/processed/  (mirrors raw tree)
    → chunker (structure-aware; see below)
    → knowledge/indexer (embeddings + BM25)
    → indexes on disk under data/indexes/
```

**Incremental ingest** (default): `scripts/ingest.py` compares each raw file’s `mtime` and size to its processed sidecar (`.meta.json`). New or changed files are parsed and written to `data/processed/`; unchanged files are skipped. When raw files are removed, the matching processed `.md` and sidecar are deleted (orphan cleanup). Single-file ingest skips cleanup; directory or full-tree runs enable it. See [ingest.md](../usage/ingest.md#orphan-cleanup-raw-deleted).

**Incremental index** (default): `scripts/index.py` compares each processed document’s `source_mtime` and `source_size` to the last build’s `manifest.json` fingerprints. New or changed documents are re-chunked and re-embedded; unchanged documents reuse existing rows; documents removed from `data/processed/` are dropped from the index (or the entire index is cleared when no processed documents remain). Pass `--force` to rebuild everything (required after chunker config changes).

After deleting raw files, run ingest + index together:

```bash
python scripts/sync.py
```

Or separately:

```bash
python scripts/ingest.py   # removes orphaned processed outputs
python scripts/index.py    # drops removed documents from the index
```

## Query (read path)

```
User question (via Open WebUI → api/)
    → metadata filter (project, build, document_type)
    → scope expansion: build → + project/common → + global  (when scope_inheritance=true)
    → retrieval/ (embedding + BM25 + merge + rerank)
    → section expansion (optional; merge sibling chunks — see below)
    → top context blocks with Citations
    → generation/ (prompt template + local LLM)
    → answer with citations
```

## Chunking and context strategy

EE-Wiki does **not** use one chunk per file. It uses **small chunks for recall, full sections for generation**:

| Stage | Unit | Purpose |
|-------|------|---------|
| **Index** | Chunk (~≤1500 chars) | Precise embedding / BM25 matching |
| **Retrieve** | Section (1+ sibling chunks) | Complete context for the LLM |

This applies to all document types and writing styles — no per-file or per-question patches.

Implementation: `src/ee_wiki/knowledge/chunker.py`, `src/ee_wiki/retrieval/section_expand.py`.

### Index time: structure-aware chunking

Split rules depend on `document_type` (see [ADR 0001](../adr/0001-chunking-strategy.md)):

| `document_type` | Primary split | Secondary split |
|-----------------|---------------|-----------------|
| `schematic` | Page boundaries (`\n---\n`) | `##` headings; `###` module blocks without overlap windows |
| All others (note, sop, datasheet, …) | Markdown `#` / `##` headings | Character window with overlap when a section exceeds `max_chars` |

**Universal boundary rules** (all prose documents):

1. **Headings only outside fenced code blocks** — lines like `# OS Mode:` inside ` ```shell ` are shell comments, not Markdown sections. Without this, a single procedure (e.g. “Get DUT SN”) can be split into useless fragments.
2. **Fenced code blocks are atomic** — a ` ``` … ``` ` block is never cut in the middle. Long sections are windowed on prose only; oversized code blocks are kept as one chunk even if they exceed `max_chars`.
3. **Tiny fragments merge** — sections shorter than `min_chars` merge into the previous section unless they start with a real heading.

**Chunk identifiers**

- Pattern: `{doc_stem}__{section-slug}` — e.g. `iPadManual__get-dut-sn`
- Window splits append `__w01`, `__w02`, … — e.g. `manual__power__w02`
- Each chunk carries document metadata (`project`, `build`, `document_type`, `source_file`, …) and a `citation` with `chunk_id`, `page`, `excerpt`.

Config: `config/default.yaml` → `chunking.*` (`max_chars`, `overlap_chars`, `min_chars`, `excerpt_chars`).

**Re-index after chunker changes**

```bash
python scripts/index.py --force
```

Chunk boundaries are fixed at index time; retrieval does not re-chunk. Incremental runs (`python scripts/index.py` without `--force`) skip unchanged processed documents.

### Query time: section expansion

After hybrid rerank selects `top_k_final` chunk hits, retrieval optionally **expands each hit to its full logical section**:

```
Hit: iPadManual__get-dut-sn__w01
  → merge with iPadManual__get-dut-sn, iPadManual__get-dut-sn__w02, … (same section key)
  → one context block sent to the LLM
```

Section key = `chunk_id` with trailing `__wNN` removed.

| Setting | Default | Meaning |
|---------|---------|---------|
| `retrieval.expand_sections` | `true` | Merge sibling chunks before prompt assembly |
| `retrieval.top_k_final` | `5` | Number of chunk *hits* before section merge |

Why both chunking and expansion?

- **Chunking** defines correct boundaries (heading + code block stay together when possible).
- **Section expansion** is a safety net when a long section is windowed into `__w01`, `__w02`, … — any window hit pulls in the whole section.

Section expansion does **not** merge chunks from different section slugs (e.g. `get-dut-sn` vs `os-mode`). Mis-split sections must be fixed in the chunker and re-indexed.

### What goes to the LLM

`generation/context.py` formats each retrieved (possibly merged) block as:

```
[N] source=… page=… chunk_id=…
<content>
```

The generator sees **question + these blocks only** — no direct index or database access.

### Citation links and images (query time)

After generation, citations are enriched with public URLs (config: `api.public_base_url`):

- `url` → `GET /v1/sources/{processed-path}#{section}` opens the processed document
- `images[]` → `GET /v1/assets/{processed-path}` serves images referenced in the chunk Markdown

Inline ``[N]`` markers stay in the LLM answer as plain text. Chat completions also return an Open WebUI-compatible ``sources`` array so the UI can render clickable citation chips.

## Rules

- Generators receive **question + retrieved context only** — no direct DB reads.
- Retrievers never call the LLM.
- Parsers never write indexes directly; they go through the knowledge layer.
- Do not rely on per-query synonym tables or per-document chunk overrides in `src/` — structure rules and metadata filters are the reusable mechanism.

## Related docs

- [0001-chunking-strategy.md](../adr/0001-chunking-strategy.md) — ADR with defaults and amendment history
- [api-overview.md](api-overview.md) — HTTP endpoints and queue limits
- [ingest.md](../usage/ingest.md) — ingest CLI and processed mirror layout
