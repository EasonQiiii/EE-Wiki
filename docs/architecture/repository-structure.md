# Repository Structure

This document defines the canonical layout for EE-Wiki. AI agents and contributors should follow this structure unless an ADR explicitly changes it.

## Design Goals

- **One module, one responsibility** — ingestion, retrieval, and generation never mix.
- **AI-navigable** — predictable paths, stable module boundaries, explicit contracts.
- **Offline-first** — runtime data and models live outside the repo; only schemas and config templates are versioned.
- **Replaceable implementations** — interfaces in `protocols/`; concrete backends swappable via config.

## Top-Level Layout

```
EE-Wiki/
├── AGENTS.md                 # Instructions for AI coding assistants
├── README.md                 # Product vision and architecture overview
├── pyproject.toml            # Python package and tool configuration
├── .env.example              # Environment variable template (no secrets)
├── .gitignore
│
├── config/                   # Default configuration (no secrets, no customer data)
│   ├── default.yaml          # Global settings: paths, model names, retrieval params
│   └── schema/               # JSON Schema for validated config and metadata
│       └── metadata.schema.json
│
├── docs/                     # Human- and AI-readable project documentation
│   ├── architecture/         # System design, data flow, API contracts
│   │   ├── repository-structure.md
│   │   ├── data-flow.md      # Ingestion → index → query pipeline
│   │   └── api-overview.md   # REST endpoints for Open WebUI integration
│   └── adr/                  # Architecture Decision Records
│       └── README.md
│
├── prompts/                  # Task-specific prompt templates (data, not code)
│   ├── _shared/              # scope_rules.md, graph_rules.md — injected into engineering prompts
│   ├── wiki/
│   ├── debug/
│   ├── design_review/
│   ├── fa/
│   ├── power/                # V3 P5 — power-tree answers
│   ├── rules/                # V3 P5 — engineering-rules answers
│   └── assistant/
│
├── scripts/                  # CLI entry points for operators and CI
│   ├── ingest.py             # Ingest documents into knowledge base
│   ├── index.py              # Build or rebuild embeddings / BM25 indexes
│   ├── sync.py               # Ingest + index in one command
│   ├── query.py              # Retrieval-only CLI
│   ├── ask.py                # RAG CLI (retrieval + generation)
│   ├── eval_rag.py           # Golden QA regression eval (retrieval / generation / both)
│   └── serve.py              # Start the API server
│
├── src/
│   └── ee_wiki/              # Main Python package
│       ├── __init__.py
│       │
│       ├── api/                # HTTP layer — Open WebUI / OpenAI-compatible REST
│       │   ├── auth.py         # Optional ingest API-key gate (EE_WIKI_INGEST_API_KEY)
│       │   └── routes/         # health, query, chat, sources, components, cases, graph, power, rules, projects, ingest
│       │
│       ├── ingestion/          # Parse raw files → StandardDocument (Markdown + metadata)
│       │   ├── parsers/        # markdown, prose_pdf, schematic_pdf, word, excel
│       │   ├── path_metadata.py
│       │   └── pipeline.py
│       │
│       ├── knowledge/          # Persist and query stored knowledge assets
│       │   ├── store/          # Processed mirror persistence
│       │   ├── indexer/        # Embedding + BM25 index writers
│       │   ├── chunker.py
│       │   └── loader.py       # Load processed records for indexing
│       │
│       ├── retrieval/          # Hybrid search pipeline (no LLM generation)
│       │   ├── hybrid/         # Scope filter, embed + BM25, merge, rerank
│       │   ├── graph_enrichment.py  # Optional compact graph neighborhood for RAG (V3 P5)
│       │   └── section_expand.py
│       │
│       ├── generation/         # Build prompts and call local LLM (no DB / graph-store access)
│       │   ├── templates/      # Loaders for prompts/ directory
│       │   └── llm/            # MLX and Transformers backends
│       │
│       ├── graph/              # Knowledge graph store/build/query (V3; ADR 0006)
│       ├── rules/              # Engineering rules engine (V3 P4)
│       ├── tools/              # MCP / function tools (V2+)
│       │
│       ├── protocols/          # Abstract interfaces (typing.Protocol)
│       │   ├── llm.py          # LlmBackend
│       │   ├── parser.py       # DocumentParser
│       │   ├── retriever.py    # RetrieverBackend
│       │   └── index_store.py  # IndexStoreBackend
│       │
│       └── common/             # Shared types, config loader, logging, errors
│           ├── types.py        # StandardDocument, Chunk, Metadata, Citation
│           ├── config.py
│           ├── logging.py
│           └── errors.py
│
└── tests/                      # Mirror src/ee_wiki/ module layout
    ├── ingestion/
    ├── retrieval/
    ├── generation/
    ├── api/
    └── fixtures/               # Sample markdown, metadata, small PDFs
```

## Module Boundaries

| Module | May do | Must not do |
|--------|--------|-------------|
| `ingestion/` | Parse files, extract text, emit `StandardDocument` | Retrieve, call LLM, serve HTTP |
| `knowledge/` | Store documents, chunks, embeddings, indexes | Parse raw files, generate answers |
| `retrieval/` | Filter, search, merge, rerank | Parse files, call LLM for final answer |
| `generation/` | Format context + question, invoke LLM | Access database directly, parse files |
| `api/` | Validate requests, orchestrate modules | Embed business logic duplicated from core |
| `tools/` | MCP / function tools for Open WebUI and Cursor | Duplicate retrieval logic from `retrieval/` |
| `graph/` | Own store + build + query (V3); retrieval may call queries | Generation must not import the graph store |
| `rules/` | Evaluate config-driven engineering rules over graph/cases (V3 P4) | Generation must not import the graph store |

**V3 graph (P0–P4):**

| Path | Status | Role |
|------|--------|------|
| `src/ee_wiki/protocols/graph.py` | P0 (present) | `GraphStoreBackend` / `GraphQueryBackend` protocols |
| `src/ee_wiki/graph/` | **P1–P3** | Store (JSONL), build from indexes (+ cases + power), scope-aware + power-tree query — [ADR 0006](../adr/0006-knowledge-graph-store.md) |
| `src/ee_wiki/graph/power.py` | P3 | Rail naming heuristics + `supplies` / `derived_from` extraction |
| `src/ee_wiki/graph/power_tree.py` | P3 | `PowerTreeQuery` (feeds / powers / tree / flags) |
| `src/ee_wiki/rules/` | **P4** | Engineering rules engine (YAML pack → pass/fail/insufficient) |
| `config/rules/` | P4 | Starter rule pack (`rail_presence`, `power_tree_flags`, `interface_naming`, `fa_recurrence`) |
| `data/indexes/cases.json` | P2 runtime | Debug-case records built at index time from FA metadata |
| `data/graph/` | Runtime path | On-disk JSONL graph bundle (`manifest.json` + `nodes.jsonl` + `edges.jsonl`); includes Case + Rail nodes |
| `scripts/build_graph.py` | P1+ | Post-index CLI to rebuild the graph bundle |
| `scripts/evaluate_rules.py` | P4 | Evaluate / list engineering rules |
| `src/ee_wiki/ingestion/case_fields.py` | P2 | FA frontmatter / heading → case metadata |
| `src/ee_wiki/knowledge/indexer/case_index.py` | P2 | Build/load `cases.json` |
| `src/ee_wiki/retrieval/case_lookup.py` | P2 | Case search + chunk-id boost for hybrid retrieval |
| `src/ee_wiki/api/routes/power.py` | P3 | `GET /v1/power/tree` |
| `src/ee_wiki/api/routes/rules.py` | P4 | `GET /v1/rules`, `GET /v1/rules/evaluate` |

## Standard Data Contracts

```
StandardDocument
├── content: str          # Normalized Markdown body
├── metadata: Metadata  # Validated against config/schema/metadata.schema.json
└── source_ref: str     # Original file path or URI
```

Chunks and citations are defined in `common/types.py` and must include provenance (`source_file`, `page`, `chunk_id`) for every retrieved context passed to the generator.

### Datasheet structured metadata (V2)

Datasheet ingestion (`ingestion/parsers/datasheet_pdf/fields.py`) post-processes VLM Markdown to populate optional document metadata. Table/graph/mixed pages also run `datasheet_pdf/quality.py` (VLM quality gate → OCR body fallback when heuristics fail).

| Field | Type | Example |
|-------|------|---------|
| `supply_voltage` | `list[str]` | `["3.3V", "2.0V-3.6V"]` |
| `pin_count` | `int \| null` | `144` |
| `package` | `str \| null` | `LQFP144` |
| `interfaces` | `list[str]` | `["I2C", "SPI", "RMII"]` (protocol names) |

These fields serialize in `.meta.json` for `document_type=datasheet` only and propagate to indexed chunks for metadata-aware retrieval boosts.

## Runtime Data (Not in Git)

These paths are configured in `config/default.yaml` and listed in `.gitignore`:

```
data/
├── raw/                  # Original documents — see layout below
├── processed/            # Mirrors raw/ tree (Markdown + metadata sidecars)
├── indexes/              # Vector and BM25 indexes
└── graph/                # Knowledge graph JSONL bundle (V3; ADR 0006)

models/                   # Local embedding, reranker, and LLM weights
```

### Raw layout (`data/raw/`)

```
data/raw/
├── global/                         # enterprise-wide shared (project=global, build=global)
│   └── note/ | sch/ | sop/ | datasheet/
├── {project}/                      # e.g. logan
│   ├── common/                     # project-wide shared (build=common)
│   │   └── note/ | sch/ | sop/
│   └── {build}/                    # e.g. p1
│       └── note/ | sch/ | sop/
```

Reserved names (configured in `config/default.yaml` → `data_layout`):

| Folder | Role |
|--------|------|
| `global` | Top-level enterprise library for all projects |
| `common` | Under a project — shared by every build in that project |

Ingestion derives `project`, `build`, and `document_type` from the path. `data/processed/` uses the **same relative paths** with `.md` (and optional `.meta.json`) instead of the original extension.

### Retrieval scope inheritance

When `retrieval.scope_inheritance` is true (default), a query for `{project}/{build}` searches, in order:

1. `{project}/{build}/`
2. `{project}/common/`
3. `global/`

## Version Mapping

| Path | Introduced in |
|------|----------------|
| `src/ee_wiki/ingestion`, `knowledge`, `retrieval`, `generation`, `api` | V1 |
| `prompts/`, `config/schema/metadata.schema.json` | V1 |
| `src/ee_wiki/protocols/` | V2 (parser, retriever, index_store protocols); V3 adds `graph.py` |
| `src/ee_wiki/tools/` | V2 (MCP / tool calling) |
| `src/ee_wiki/graph/` | V3 P1–P3 (store/build/query + power tree; ADR 0006) |
| `src/ee_wiki/rules/` | V3 P4 (engineering rules engine) |
| `config/rules/` | V3 P4 (YAML rule pack) |
| Multi-agent orchestration (future `src/ee_wiki/agents/`) | V4 |

## Adding New Code

1. Place code in the module that matches its single responsibility.
2. Add or extend a protocol in `protocols/` before adding a second implementation.
3. Add tests under `tests/<module>/` with fixtures, not live enterprise documents.
4. Update `docs/architecture/data-flow.md` or an ADR if the boundary changes.
5. Never add project-specific or customer-specific directories inside `src/`.

## Related Documents

- [docs/usage/local-setup.md](../usage/local-setup.md) — local machine setup and V1/V2 acceptance checklists
- [docs/usage/mcp.md](../usage/mcp.md) — V2 component lookup, MCP, HTTP ingest
- [docs/usage/ingest.md](../usage/ingest.md) — operator guide for `scripts/ingest.py`
- [docs/usage/eval.md](../usage/eval.md) — golden QA regression eval (`scripts/eval_rag.py`)
- [AGENTS.md](../../AGENTS.md) — rules for AI assistants working in this repo
- [README.md](../../README.md) — vision, principles, and roadmap
