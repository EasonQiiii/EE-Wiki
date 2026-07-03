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
│   ├── wiki/
│   ├── debug/
│   ├── design_review/
│   ├── fa/
│   ├── compare/
│   └── explain/
│
├── scripts/                  # CLI entry points for operators and CI
│   ├── ingest.py             # Ingest documents into knowledge base
│   ├── index.py              # Build or rebuild embeddings / BM25 indexes
│   ├── sync.py               # Ingest + index in one command
│   └── serve.py              # Start the API server
│
├── src/
│   └── ee_wiki/              # Main Python package
│       ├── __init__.py
│       │
│       ├── api/                # HTTP layer — Open WebUI / OpenAI-compatible REST
│       │   ├── routes/
│       │   └── middleware/
│       │
│       ├── ingestion/          # Parse raw files → StandardDocument (Markdown + metadata)
│       │   ├── parsers/        # pdf, docx, pptx, xlsx, markdown, image/ocr
│       │   └── pipeline.py
│       │
│       ├── knowledge/          # Persist and query stored knowledge assets
│       │   ├── store/          # Document, chunk, metadata persistence
│       │   └── indexer/        # Embedding + BM25 index writers
│       │
│       ├── retrieval/          # Hybrid search pipeline (no LLM generation)
│       │   ├── filters/        # Metadata pre-filter
│       │   ├── embedder/
│       │   ├── bm25/
│       │   ├── merger/
│       │   └── reranker/
│       │
│       ├── generation/         # Build prompts and call local LLM (no DB access)
│       │   ├── templates/      # Loaders for prompts/ directory
│       │   └── llm/            # Ollama / vLLM / other offline backends
│       │
│       ├── graph/              # Knowledge graph (V3+) — nodes, edges, queries
│       │
│       ├── tools/              # Tool definitions for MCP / function calling (V2+)
│       │
│       ├── protocols/          # Abstract interfaces (typing.Protocol / ABC)
│       │   ├── parser.py
│       │   ├── retriever.py
│       │   ├── generator.py
│       │   └── knowledge_store.py
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
| `graph/` | Store and query engineering relationships | Replace retrieval for document Q&A in V1 |
| `tools/` | Expose callable tools to MCP / Open WebUI | Implement retrieval logic inline |

## Standard Data Contracts

All parsers output the same shape:

```
StandardDocument
├── content: str          # Normalized Markdown body
├── metadata: Metadata  # Validated against config/schema/metadata.schema.json
└── source_ref: str     # Original file path or URI
```

Chunks and citations are defined in `common/types.py` and must include provenance (`source_file`, `page`, `chunk_id`) for every retrieved context passed to the generator.

## Runtime Data (Not in Git)

These paths are configured in `config/default.yaml` and listed in `.gitignore`:

```
data/
├── raw/                  # Original documents — see layout below
├── processed/            # Mirrors raw/ tree (Markdown + metadata sidecars)
├── indexes/              # Vector and BM25 indexes
└── graph/                # Graph database files (V3+)

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
| `src/ee_wiki/tools/` | V2 (MCP / tool calling) |
| `src/ee_wiki/graph/` | V3 |
| Multi-agent orchestration (future `src/ee_wiki/agents/`) | V4 |

## Adding New Code

1. Place code in the module that matches its single responsibility.
2. Add or extend a protocol in `protocols/` before adding a second implementation.
3. Add tests under `tests/<module>/` with fixtures, not live enterprise documents.
4. Update `docs/architecture/data-flow.md` or an ADR if the boundary changes.
5. Never add project-specific or customer-specific directories inside `src/`.

## Related Documents

- [docs/usage/ingest.md](../usage/ingest.md) — operator guide for `scripts/ingest.py`
- [AGENTS.md](../../AGENTS.md) — rules for AI assistants working in this repo
- [README.md](../../README.md) — vision, principles, and roadmap
