# AGENTS.md — AI Assistant Guide for EE-Wiki

This file is the primary instruction set for AI coding assistants (Cursor, Codex, Claude Code, Gemini CLI, OpenAI Agents) working in this repository.

Humans define architecture. AI implements details within these boundaries.

---

## 1. Project Identity

| Item | Value |
|------|-------|
| **Name** | EE-Wiki |
| **Purpose** | Offline, AI-native electronic engineering knowledge platform |
| **Role** | Backend knowledge engine; Open WebUI is the frontend |
| **Current phase** | V2 — engineering metadata, component DB, datasheet parser, MCP tools |

Read [README.md](README.md) for vision and principles — especially [Raw Data Layout](README.md#raw-data-layout) and [Retrieval Scope](README.md#retrieval-scope). Read [docs/architecture/repository-structure.md](docs/architecture/repository-structure.md) before creating or moving files.

---

## 2. Non-Negotiable Principles

### Modular boundaries

- **Parser** never retrieves or generates.
- **Retriever** never parses or generates final answers.
- **Generator** never accesses the database or parses raw documents.
- **Knowledge** layer never depends on UI or HTTP framework details.

If a change crosses these lines, stop and propose an ADR instead of merging logic.

### Knowledge first

- LLMs reason and write; they are not the source of truth.
- Every generated answer must be grounded in retrieved context with **citations** (document, page, chunk).
- Answers must **explicitly distinguish** `project` / `build` and knowledge layer (`build` vs project `common` vs `global`) — see README [Retrieval Scope](README.md#retrieval-scope) and `prompts/_shared/scope_rules.md`.
- When context is insufficient, return an explicit “insufficient knowledge” response — never invent part numbers, nets, or pin assignments.

### Offline first

- No required cloud APIs, telemetry, or external model hosts.
- Configuration drives local model paths and data directories.
- Do not add dependencies that phone home or require internet at runtime.

### Reusability

- No project-specific parsers, prompts, or hardcoded build/project names in `src/`.
- Customer or project scope belongs in **metadata filters** and **config**, not in code branches.

---

## 3. Repository Map (Quick Reference)

```
src/ee_wiki/
├── api/           → HTTP routes, request/response models
├── ingestion/     → File parsers → StandardDocument
├── knowledge/     → Storage, chunking, indexing
├── retrieval/     → Metadata filter → embed + BM25 → merge → rerank
├── generation/    → Prompt assembly + local LLM
├── graph/         → Knowledge graph store/build/query (V3 P1–P3)
├── connectivity/  → Schematic connectivity sidecar query (ADR 0009; HTTP/MCP trace)
├── rules/         → Engineering rules engine (V3 P4)
├── tools/         → MCP / function tools (V2)
├── integrations/  → FA connectors: Radar / Flames / Keynote (ADR 0010; stub by default)
├── protocols/     → Interfaces all implementations must satisfy
└── common/        → Types, config, logging, errors

prompts/           → YAML or Markdown prompt templates by task
config/            → default.yaml + JSON Schema
assets/templates/fa/ → Company FA Keynote template (one_page.key)
data/raw/          → Original documents (gitignored); path = metadata
data/processed/    → Mirrors data/raw/ tree after ingestion
data/exports/      → FA Keynote summaries (gitignored); GET /v1/exports/
data/cache/        → FA Flames/Radar cache (gitignored); GET /v1/cache/
docs/architecture/ → Data flow, API contracts
tests/             → Mirrors src layout; fixtures only, never enterprise raw data
```

Do not create parallel top-level packages or duplicate module names outside this layout.

---

## 4. Raw Data & Retrieval Scope

Raw files live under `data/raw/` using a three-level scope hierarchy —
`product` / `project` / `build` — plus two reserved words ([ADR 0011](docs/adr/0011-product-project-build-hierarchy.md)):

```
global/{type}/<file>                        → product=global, project=global, build=global
{product}/common/{type}/<file>              → product common (project=common, build=common)
{product}/{project}/common/{type}/<file>    → project common (build=common)
{product}/{project}/{build}/{type}/<file>   → build truth
```

Reserved segments (see `config/default.yaml` → `data_layout`):

| Segment | Location | Meaning | Purpose |
|---------|----------|---------|---------|
| `global` | `data/raw/global/` | Enterprise-wide shared (`product`=`project`=`build`=`global`) | All products: generic tools, industry practices, common datasheets |
| `common` (product) | `data/raw/{product}/common/` | Shared by all projects in that product | Product-wide knowledge: platform architecture, naming, cross-project SOPs |
| `common` (project) | `data/raw/{product}/{project}/common/` | Shared by all builds in that project | Project-wide knowledge — not board-specific wiring |
| `{build}` | e.g. `p1` | A specific hardware build | Build truth: schematics and docs for that revision |

`global` and `common` are **reserved** — they may not be used as ordinary product/project/build slugs.

Document folders: `note`, `sch`, `sop`, `datasheet`, `fa` → map to `document_type` via `data_layout.document_type_folders`.

**Ingestion must:**

- Derive `product`, `project`, `build`, `document_type` from the path — do not hardcode names in code.
- Write outputs to `data/processed/` with the **same relative path** as `data/raw/` (`.md` + optional `.meta.json`).
- Set `metadata.build` (never `board`).

**Retrieval must:**

- Apply `retrieval.scope_inheritance` from config (default `true`).
- When filtering `product=P, project=X, build=Y`, expand scope upward: build truth → project common → product common → `global`.
- Rank build-specific chunks above project `common`, project `common` above product `common`, and product `common` above `global`.

V1 raw formats: PDF, Markdown, TXT, Excel, Word (`.doc`/`.docx`). On macOS, Keynote (`.key`) and Numbers (`.numbers`) via AppleScript export ([ADR 0004](docs/adr/0004-iwork-macos-export.md)); elsewhere skip with a clear log message.

---

## 5. Coding Standards

Apply to all Python under `src/` and `tests/`:

- Type hints on every public function and method.
- Docstrings on every public function (Args, Returns, Raises where relevant).
- Structured logging via `common/logging.py` — no bare `print` in library code.
- Explicit error types from `common/errors.py`; catch narrowly, log with context, re-raise or map to API errors.
- Prefer composition and `typing.Protocol` over deep inheritance.
- Prefer configuration (`config/default.yaml`) over hardcoded constants.
- Prefer local LLM + `prompts/` for **semantic** intent (evidence vs chat, task/role route); reserve regex for **structural** tokens (Radar ids, URLs, path segments).
- Keep functions focused; extract when a file exceeds ~300 lines or a class has more than one reason to change.

### Public function checklist

```python
def search_chunks(query: str, filters: MetadataFilter) -> list[Chunk]:
    """Search indexed chunks matching query and metadata filters.

    Args:
        query: Natural language or keyword search string.
        filters: Project/build/document_type constraints.

    Returns:
        Ranked chunks with citation metadata attached.

    Raises:
        RetrievalError: If indexes are unavailable or corrupt.
    """
```

---

## 6. What to Do / What Not to Do

### Do

- Extend `protocols/` before adding a second backend (e.g. a new vector store).
- Add tests alongside new behavior in `tests/<module>/`.
- Implement path → metadata parsing in `ingestion/` using `config/default.yaml` → `data_layout`.
- Implement scope expansion in `ingestion/path_metadata.py` (`expand_retrieval_scope`) and `retrieval/hybrid/engine.py` (`_filter_by_scope`), driven by `retrieval.scope_inheritance`.
- Validate metadata against `config/schema/metadata.schema.json`.
- Keep prompt text in `prompts/`, loaded by `generation/templates/`; shared scope rules live in `prompts/_shared/scope_rules.md`.
- Use ADRs in `docs/adr/` for non-trivial technology or boundary decisions.
- Match existing naming, import order, and error-handling patterns in neighboring files.

### Do not

- Put retrieval logic inside `api/` route handlers beyond orchestration.
- Import `generation` from `ingestion` or `retrieval` (dependency direction: ingestion → knowledge → retrieval → generation → api).
- Commit secrets, enterprise documents, or model weights.
- Add OpenAI/cloud-only code paths without an offline equivalent and config flag.
- Expand scope beyond the user’s request (no drive-by refactors).
- Use metadata field `board` — always use `build`.
- Create markdown files the user did not ask for.

---

## 7. Dependency Direction

Allowed import flow (higher may depend on lower, never reverse):

```
api
  ↓
generation, tools, graph, rules (orchestration layers)
  ↓
retrieval
  ↓
knowledge
  ↓
ingestion
  ↓
common, protocols
```

`protocols/` and `common/` must not import from feature modules.

---

## 8. Version Scope Guardrails

When implementing, respect the roadmap in README.md:

| Version | In scope | Out of scope |
|---------|----------|--------------|
| **V1** | Markdown/PDF ingest, hybrid retrieval, citations, Open WebUI REST, local LLM | Knowledge graph, multi-agent, schematic CAD parsing |
| **V2** | Rich metadata, component DB, datasheet parser, MCP tools | Full graph reasoning, agent swarms |
| **V3** | Knowledge graph, debug case DB, power tree | Full CAD netlist import, cloud graph DBs |
| **V4** | Multi-agent orchestration ([ADR 0008](docs/adr/0008-multi-agent-runtime.md), accepted: Supervisor + ToolBus + six config roles) | Day-1 landed: see [docs/usage/agents.md](docs/usage/agents.md) |

**V3 progress:**

- **P0 (boundaries)** — [ADR 0006](docs/adr/0006-knowledge-graph-store.md): offline JSONL graph bundle under `data/graph/`; `protocols/graph.py`
- **P1 (core)** — `src/ee_wiki/graph/` store + build + query; build from `chunks.jsonl` / schematic page fields / `components.json`; `scripts/build_graph.py` → `data/graph/`
- **P2 (debug cases)** — FA/debug case schema on `failure_analysis` metadata; `data/indexes/cases.json`; Case graph nodes (`mentions` / `caused_by` / `related_to`); retrieval case lookup + boost; `GET /v1/cases/search` + MCP `search_debug_case_tool`
- **P3 (power tree)** — Rail nodes + `supplies` / `derived_from` heuristics from schematic nets + datasheet `supply_voltage`; `PowerTreeQuery`; `GET /v1/power/tree` + MCP `query_power_tree_tool`; config `graph.power_tree`
- **P4 (engineering rules)** — YAML rule pack under `config/rules/`; `src/ee_wiki/rules/` engine (pass/fail/insufficient + citations); starter checks for rail presence, power-tree flags, interface naming, FA recurrence; `GET /v1/rules` + `/v1/rules/evaluate` + MCP `list_rules_tool` / `evaluate_rules_tool` + `scripts/evaluate_rules.py`; config `rules.enabled` / `rules.pack_dir`
- **P5 (API / MCP / prompts wrap-up)** — `GET /v1/graph/{node,neighbors,path,nodes}` + MCP `open_graph_node_tool` / `graph_neighbors_tool` / `graph_path_tool` / `graph_filter_tool`; graph-aware prompts (`prompts/_shared/graph_rules.md`, `prompts/power/`, `prompts/rules/`); optional `retrieval.graph_enrichment` (default **false**) attaches compact neighborhood text to RAG context without generation importing the store. **V3 complete** (CAD netlist import and cloud graph DBs remain out of scope).

**V2 progress (implemented):**

- **Datasheet Parser** — VLM page-level extraction with page classification (text/table/graph/mixed), auto-dispatch for `datasheet/` paths
- **Datasheet structured fields** — `supply_voltage`, `pin_count`, `package`, `interfaces` on datasheet metadata (regex heuristics post-VLM)
- **Engineering Metadata** — automatic keyword extraction (part numbers, voltages, protocols, packages) during ingestion; populates `keywords` for metadata boost
- **FA metadata** — `fa/` → `failure_analysis`; FA-specific keywords (failure modes, symptoms, RMA/LOT/DATECODE tokens)
- **Debug Case Database (V3 P2)** — structured case fields on FA docs (frontmatter / headings → `.meta.json`); `cases.json` index; Case graph links; config-gated retrieval boost + case search API/MCP
- **Chunk-level schematic metadata** — per-page `major_components` / `nets` / `interfaces` on indexed chunks via `pages` sidecar
- **Component Database** — `data/indexes/components.json`, retrieval boost, `GET /v1/components/search`
- **Index inventory** — `GET /v1/projects`, chat inventory questions, MCP `list_projects_tool`; ScopeCatalog includes common-only products
- **HTTP ingest admin** — `POST /v1/ingest` (sync or `async: true` → 202 + job poll); optional `EE_WIKI_INGEST_API_KEY`
- **Datasheet VLM quality gate** — table/graph/mixed pages fall back to OCR body when heuristics fail (`datasheet_pdf/quality.py`)
- **MCP Tools** — read-only tools in `src/ee_wiki/tools/` via `scripts/mcp_serve.py`
- **Protocols** — `protocols/parser.py`, `protocols/retriever.py`, `protocols/index_store.py` (stubs before second backends); V3 adds `protocols/graph.py` (ADR 0006)

If a task belongs to a future version, implement a **protocol + stub** or document the interface only — do not build the full feature unless explicitly requested.

---

## 9. Testing Expectations

- Unit tests for path → metadata parsing, scope expansion, parsers, chunkers, retrieval merge/rerank.
- Integration tests with fixtures in `tests/fixtures/` (small synthetic docs only).
- No tests that require downloaded models in CI unless marked optional/slow.
- Mock LLM and embedding backends in tests; do not call real inference in default test runs.

Run before proposing completion:

```bash
pytest
ruff check src tests
```

(Commands assume `pyproject.toml` tooling is configured; if not yet present, note that in the PR.)

---

## 10. Configuration and Secrets

- Secrets and local paths: `.env` (gitignored), template in `.env.example`.
- Non-secret defaults: `config/default.yaml` — including `data_layout` (path segment names) and `retrieval.scope_inheritance`.
- Never commit API keys, internal hostnames, or customer document paths.

---

## 11. API and Open WebUI Integration

- EE-Wiki exposes backend REST endpoints; Open WebUI handles chat UI, auth, and model management.
- Prefer OpenAI-compatible shapes where practical for chat completions.
- Document new endpoints in `docs/architecture/api-overview.md`.
- Streaming, tool calling, and MCP are incremental — implement behind clear feature flags.

---

## 12. Documentation Updates

When your change affects structure or behavior, update the minimal set:

| Change type | Update |
|-------------|--------|
| Answer must distinguish project/build and knowledge layer | `prompts/_shared/scope_rules.md`, `prompts/*/default.md`, `generation/context.py`, README Retrieval Scope |
| Knowledge authoring / placement rules | `docs/usage/knowledge-authoring.md` |
| Raw path convention or scope rules | `README.md` (Raw Data / Retrieval Scope) + this file §4 + `.cursor/rules/raw-data-retrieval.mdc` |
| Ingest CLI behavior or flags | `docs/usage/ingest.md` |
| RAG golden QA / eval CLI | `docs/eval/qa.md`, `docs/eval/qa.yaml`, `docs/usage/eval.md` |
| New module or directory | `docs/architecture/repository-structure.md` |
| Pipeline or data contract | `docs/architecture/data-flow.md` |
| New HTTP endpoint | `docs/architecture/api-overview.md`, `docs/usage/mcp.md` (V2 tools) |
| Technology choice | New file under `docs/adr/` |
| User-facing vision shift | `README.md` (only when asked) |

---

## 13. Commit and PR Conventions

- One logical change per commit; message explains **why**, not only what.
- Do not commit unless the user explicitly asks.
- PR summary: problem, approach, test plan, screenshots/logs if API behavior changed.

---

## 14. Example Tasks (How to Approach)

### “Add PDF parser”

1. Implement `ingestion/parsers/pdf.py` returning `StandardDocument`.
2. Add `ingestion/path_metadata.py` (or equivalent) to derive `project`, `build`, `document_type` from `data/raw/` relative path.
3. Register in ingestion pipeline; write output under `data/processed/` mirroring the raw path.
4. Add fixture under `tests/fixtures/` mimicking `iphone/logan/p1/sch/sample.pdf`; tests in `tests/ingestion/`.
5. Extend metadata schema only if new fields are required for all document types.

### “Add debug prompt”

1. Add template under `prompts/debug/`.
2. Wire loader in `generation/templates/`; no inline prompt strings in Python.
3. Test template rendering with mock context chunks.

### “Expose search API”

1. Add route in `api/routes/` calling `retrieval` service.
2. Map errors to HTTP status codes in one place.
3. Document request/response in `docs/architecture/api-overview.md`.

---

## 15. Glossary

| Term | Meaning |
|------|---------|
| **project** | Product or program name; path segment under `data/raw/` (e.g. `logan`) |
| **build** | Hardware build or revision (e.g. `p1`); metadata field — not `board` |
| **StandardDocument** | Normalized parser output: Markdown + metadata + source reference |
| **Chunk** | Indexed segment with citation and embedding |
| **Processed mirror** | `data/processed/` keeps the same relative paths as `data/raw/` |
| **Scope inheritance** | Retrieval for `build=Y` also searches `{project}/common/` and `global/` |
| **Metadata filter** | Pre-retrieval filter on project, build, document_type |
| **global** | Enterprise-wide shared raw path: `data/raw/global/` | All-project knowledge: tools, industry practices, generic datasheets |
| **common** | Project-wide shared raw path: `data/raw/{project}/common/` | That project's cross-build knowledge — not another project's, not build-specific wiring |
| **Hybrid retrieval** | Metadata filter → embedding + BM25 → merge → rerank |
| **Citation** | Provenance attached to every context block shown to the LLM |

---

## 16. Resolved Technology Choices (ADR)

V1 baseline is decided — do not re-litigate without a new ADR:

| Topic | Decision | Reference |
|-------|----------|-----------|
| Chunking | Structure-aware; schematic page boundaries | [ADR 0001](docs/adr/0001-chunking-strategy.md) |
| Index storage | Flat on-disk hybrid bundle (`data/indexes/`) | [ADR 0002](docs/adr/0002-v1-runtime-stack.md) |
| Embedding / reranker | `sentence-transformers`; paths in `config/default.yaml` | ADR 0002 |
| Local LLM | MLX default; Transformers alternative; external OpenAI-compatible HTTP (`openai`) per ADR 0003 | ADR 0002, ADR 0003 |
| Knowledge graph store | Offline JSONL bundle under `data/graph/`; `graph/` owns store/build/query; generation never imports store; P2 cases live in `data/indexes/cases.json` and as Case nodes in the graph | [ADR 0006](docs/adr/0006-knowledge-graph-store.md) |
| Multi-agent runtime (V4) | Supervisor + read-only ToolBus; config-driven roles; agents must not write graph/ingest (**accepted**) | [ADR 0008](docs/adr/0008-multi-agent-runtime.md) |
| Chat pipeline grounding | Gates once at chat; rules-first route; agent turns → hybrid RAG + citations (`task_owner`) | [ADR 0012](docs/adr/0012-chat-pipeline-grounding.md) |
| Schematic connectivity map | PDF + BoardView `.brd` + netlist complementary merge into `*.connectivity.json` (v2) | [ADR 0009](docs/adr/0009-multi-source-schematic-map.md), [ADR 0007](docs/adr/0007-schematic-connectivity-extraction.md) |
| FA session (Radar-keyed) | Open WebUI session keyed by Radar id; Flames/Radar protocols + stubs; Keynote under `data/exports/fa/{radar_id}/`; download via `/v1/exports` (**proposed**) | [ADR 0010](docs/adr/0010-fa-session-external-integrations.md) |

**Still open (V2+):** external vector DB (Qdrant, pgvector), Ollama/vLLM/llama.cpp — require a new ADR before adoption. Heavier graph backends (SQLite/NetworkX persistence, Neo4j embedded) require amending ADR 0006 or a follow-up ADR. Debate-style or write-back agent paradigms require amending ADR 0008.

---

*Last updated: V3 P5 — graph HTTP/MCP suite, graph-aware prompts, optional retrieval↔graph enrichment (V3 wrap-up).*
