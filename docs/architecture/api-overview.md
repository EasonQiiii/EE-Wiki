# API Overview

EE-Wiki serves as the backend for Open WebUI. This document tracks the HTTP surface area.

**Status:** V3 — knowledge graph, debug cases, power tree, engineering rules, graph HTTP/MCP suite (see [Long-term Roadmap](#long-term-roadmap) in README).

## Scope filters (`product` / `project` / `build`)

Strongly recommended for engineering questions. `product` is required whenever `project` or `build` is set.

| Field | Meaning |
|-------|---------|
| `product` | Product line (e.g. `iphone`) |
| `project` | Program within the product (e.g. `logan`) |
| `build` | Hardware revision (e.g. `p1`) or `common` for project-wide-only queries |

When all three are set with `retrieval.scope_inheritance: true` (default), search expands to `{product}/{project}/{build}` → `{product}/{project}/common` → `{product}/common` → `global`. Answers must label conclusions by scope (`build`, project `common`, product `common`, `global`). Omitting scope fields searches the entire index.
## Implemented endpoints (V1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness for deployment |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `GET` | `/v1/sources/{path}` | Processed Markdown/text document mirror (citation `url` now points at `/v1/raw`) |
| `GET` | `/v1/raw/{path}` | Original raw document for citation **download** links |
| `GET` | `/v1/assets/{path}` | Image or asset under `data/processed/` |
| `POST` | `/v1/query` | Explicit RAG query with citation payload |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (retrieval + generation); set `"stream": true` for SSE |

## Implemented endpoints (V2)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/components/search` | Part number / designator lookup against `data/indexes/components.json` |
| `GET` | `/v1/projects` | Indexed product/project/build inventory (chunk counts; `global` flagged as enterprise) |
| `POST` | `/v1/ingest` | Trigger document ingestion and optional index build (admin; sync by default, or `async: true` → 202) |
| `GET` | `/v1/ingest/jobs/{job_id}` | Poll async ingest job status (`queued` / `running` / `succeeded` / `failed`) |

## Implemented endpoints (V3)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/cases/search` | Debug / FA case lookup against `data/indexes/cases.json` (P2) |
| `GET` | `/v1/power/tree` | Heuristic power-tree query against `data/graph/` (P3) |
| `GET` | `/v1/rules` | List engineering rules from `config/rules/` (P4) |
| `GET` | `/v1/rules/evaluate` | Evaluate engineering rules against graph + cases (P4) |
| `GET` | `/v1/graph/node` | Resolve and open one graph node (P5) |
| `GET` | `/v1/graph/neighbors` | Neighbor nodes within N hops (P5) |
| `GET` | `/v1/graph/path` | Shortest path between two nodes (P5) |
| `GET` | `/v1/graph/nodes` | Filter nodes by product/project/build scope (P5) |
| `GET` | `/v1/schematic/connectivity/net` | Trace pins on a net from `*.connectivity.json` (ADR 0009) |
| `GET` | `/v1/schematic/connectivity/pins` | Pin↔net list for a designator / connector |
| `GET` | `/v1/schematic/connectivity/module-nets` | Nets for a page module zone label |

## FA session artifacts (ADR 0010)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/exports/{path}` | Download under `data/exports/` (e.g. `fa/{radar_id}/FA_summary.key`) |
| `GET` | `/v1/cache/{path}` | Download under `data/cache/` (e.g. Flames logs `fa/{radar_id}/*.log`) |

Orchestration helpers live in `ee_wiki.integrations.session` (`start_fa_checkin`, `generate_fa_summary`, confirm-gated Radar writes). Open WebUI chat intent wiring lands with the FA supervisor (ADR 0008 + 0010). Set `api.public_base_url` so assistant markdown links are browser-reachable.

See [fa-session.md](fa-session.md), [integrations-radar.md](integrations-radar.md), [integrations-flames.md](integrations-flames.md).

Query params for `GET /v1/components/search`: `q` (required), optional `project`, `build`, `limit` (default 20).

Query params for `GET /v1/cases/search`: `q` (required — symptom, part, net, or case id), optional `project`, `build`, `limit` (default 20). Hits include `case_id`, `symptom`, `suspected_*`, `root_cause`, `source_file`, and `chunk_ids` for citation.

Query params for `GET /v1/power/tree`: optional `q` (rail / designator / part; required unless `direction=flags`), `direction` (`feeds` | `powers` | `tree` | `flags`, default `tree`), optional `project`, `build`, `max_depth` (default 4). Returns heuristic `supplies` / `derived_from` neighbors, optional indented `tree` text, and/or diagnostic `flags`. Requires a built graph (`python scripts/build_graph.py`); 503 if missing.

Query params for `GET /v1/rules`: optional `include_disabled` (default false). Returns rule ids, check types, severity, and params from `config/rules/`.

Query params for `GET /v1/rules/evaluate`: optional `project`, `build`, repeatable `rule_id`, optional `include_disabled`. Returns pass/fail/insufficient results with citations (graph node / case / chunk refs). Requires a built graph; 503 if rules disabled or graph/pack missing. CLI: `python scripts/evaluate_rules.py [--project X] [--build Y] [--rule id]`.

Query params for `GET /v1/graph/node`: `q` (required — node id or designator/net/rail/case/part), optional `project`, `build`.

Query params for `GET /v1/graph/neighbors`: `q` (required), optional `project`, `build`, `max_hops` (default 1), `edge_types` (comma-separated allowlist).

Query params for `GET /v1/graph/path`: `source` and `target` (required), optional `project`, `build`, `max_depth` (default 8), `edge_types`. Returns `found` plus alternating node/edge steps when a path exists.

Query params for `GET /v1/graph/nodes`: optional `project`, `build`, `node_types` (comma-separated), `limit` (default 200). Scope inheritance follows `graph.scope_inheritance`.

Query params for `GET /v1/schematic/connectivity/net`: `q` (required — net name), optional `project`, `build`, `source_file` (path substring). Returns pin bindings with `evidence` tags (`cad_netlist` / …). **Authoritative-only gate (ADR 0009 §5):** with `connectivity.require_authority_for_trace` (default `true`), a trace is returned only when grounded on `cad_netlist` (BoardView `.brd` is advisory-only and never grounds a trace); if only geometry/OCR evidence exists the route returns **409** (`authority: "insufficient"`) and lists suppressed data under `advisory_pins`. Requires re-ingested schematic sidecars; 503 if none loaded, 404 if net not found in any tier. Response adds `authoritative` (bool), `authority` (`authoritative` / `advisory` / `insufficient` / `not_found`), `advisory_pins`, `advisory_connectors`, `note`.

Query params for `GET /v1/schematic/connectivity/pins`: `q` (required — designator), optional `project`, `build`, `source_file`. Returns `pins` from document-level parts (authoritative) plus optional page-level `connectors` (advisory). Same authoritative-only gate as `/net` (409 when only advisory evidence).

Query params for `GET /v1/schematic/connectivity/module-nets`: `q` (required — module zone label), optional `project`, `build`, `source_file`, `page` (1-based). Returns page-scoped `module_nets` from the sidecar. Module zone labels are geometric **locators**, not verified traces — always tagged `authority: "advisory"`.

Optional RAG enrichment: set `retrieval.graph_enrichment: true` to attach a compact `[graph]` neighborhood block to chat/query context (default **false**; generation still never opens the store).

Chat inventory questions such as “当前知识库有多少 project” are answered from the same index metadata (deterministic text; no document RAG).

### `POST /v1/ingest`

Admin endpoint to run the same pipeline as `scripts/sync.py` (ingest raw → processed, then build/update indexes). Orchestrates existing `ingest_path` and `build_index_from_processed` — no parsing logic in the route.

Request (all fields optional):

```json
{
  "path": "iphone/logan/p1/fa/rma-report.md",
  "paths": null,
  "product": "iphone",
  "project": "logan",
  "build": "p1",
  "force": false,
  "ingest_only": false,
  "index_only": false,
  "async": false
}
```

| Field | Meaning |
|-------|---------|
| `path` | Single file or directory under `data/raw/` (relative, `data/raw/...`, or absolute under raw dir) |
| `paths` | List of paths (mutually exclusive with `path`) |
| `product` / `project` / `build` | When no path given, scope under `data/raw/{product}/…` |
| `force` | Re-ingest and rebuild even when fingerprints match |
| `ingest_only` | Skip index build (like `scripts/sync.py --ingest-only`) |
| `index_only` | Skip ingest (like `scripts/sync.py --index-only`) |
| `async` | When `true`, return **202 Accepted** with a `job_id` and run ingest in the background (default `false` = synchronous 200) |

When all path filters are omitted, the entire `data/raw/` tree is processed.

**Synchronous response** (`async` omitted or `false`) — HTTP 200:

```json
{
  "ingested": 2,
  "skipped": 5,
  "removed": 0,
  "ingested_files": ["data/processed/iphone/logan/p1/fa/rma-report.md"],
  "removed_files": [],
  "indexed_documents": 2,
  "skipped_documents": 5,
  "removed_documents": 0,
  "chunk_count": 42
}
```

Index fields (`indexed_documents`, `skipped_documents`, `removed_documents`, `chunk_count`) are `null` when `ingest_only: true`. Ingest counts are zero when `index_only: true`.

**Async accept** (`"async": true`) — HTTP 202:

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "status_url": "/v1/ingest/jobs/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Ingest job accepted; poll status_url for progress"
}
```

(`status_url` is absolute when `api.public_base_url` is set.)

### `GET /v1/ingest/jobs/{job_id}`

Poll an async ingest job. Status values: `queued` | `running` | `succeeded` | `failed`.

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "succeeded",
  "created_at": "2026-07-13T01:00:00+00:00",
  "started_at": "2026-07-13T01:00:01+00:00",
  "finished_at": "2026-07-13T01:05:00+00:00",
  "error": null,
  "result": {
    "ingested": 2,
    "skipped": 5,
    "removed": 0,
    "indexed_documents": 2,
    "chunk_count": 42
  }
}
```

On failure, `status` is `failed`, `error` holds the message, and `result` is `null`. Unknown `job_id` → 404.

**Concurrency:** `api.max_concurrent_ingest_jobs` (default `1`) limits how many async ingest jobs run at once; additional jobs stay `queued` until a slot frees. Jobs are **in-memory only** and are lost on server restart (single-process FastAPI; no Redis/Celery).

**Auth (optional):** when `EE_WIKI_INGEST_API_KEY` is set, both `POST /v1/ingest` and `GET /v1/ingest/jobs/{job_id}` require `X-API-Key: <secret>` or `Authorization: Bearer <secret>` (401 otherwise). When unset, ingest stays open; binding `api.host` to `0.0.0.0` without a key logs a startup warning. Chat/query/components are not gated.

Errors on `POST /v1/ingest`: `400` for invalid paths or conflicting flags; `401` when the ingest API key is required but missing/wrong; `404` when the target path does not exist (sync path, or pre-accept validation); `500` when index build fails on the sync path (e.g. no processed documents on first run). Async pipeline errors surface on the job poll as `failed`.

## Planned endpoints (V2+)

| Method | Path | Purpose |
|--------|------|---------|
| — | — | — |

## Start the server

```bash
pip install -e ".[dev,ml,mlx,api]"
python scripts/serve.py
```

RAG/chat uses `generation.llm_backend`:

| Backend | Runtime | Multi-user |
|---------|---------|------------|
| `mlx` (default) | In-process `mlx-lm` | No (`max_concurrent` capped at 1) |
| `transformers` | In-process Hugging Face | Limited (configure `max_concurrent`) |
| `openai` | External OpenAI-compatible HTTP API ([ADR 0003](../adr/0003-external-llm-openai-compatible.md)) | Yes — use with mlx-openai-server |

Model paths: `models.llm_mlx_model`, `models.llm_transformers_model`, or `generation.openai_*` depending on backend. Schematic PDF ingest still uses `models.visual_model` (Qwen3-VL via transformers).

Default bind: `0.0.0.0:8080` (see `config/default.yaml` → `api`).

Set `api.warmup_on_startup: true` to preload the index, embedding model, reranker, and LLM when the server starts (recommended for Open WebUI; first startup may take several minutes).

## Concurrency and queue limits

LAN deployments use a bounded queue on `/v1/query` and `/v1/chat/completions`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `api.concurrency.max_concurrent` | `1` | Active RAG requests (`mlx` in-process is always capped at 1; `openai` backend: try `6` on 48 GB) |
| `api.concurrency.max_queue_depth` | `8` | Additional requests allowed to wait (`openai` backend: try `12`) |
| `api.concurrency.retry_after_seconds` | `15` | `Retry-After` when queue is full |
| `api.request_timeout_seconds` | `300` | Whole RAG request wall-clock cap (`504` when exceeded; `null` or `0` disables) |

Generation timeouts:

| Setting | Default | Meaning |
|---------|---------|---------|
| `generation.max_new_tokens` | `2048` | Maximum LLM output tokens per answer |
| `generation.llm_timeout_seconds` | `180` | LLM generation cap (`504` via request handler; `null` or `0` disables) |
| `generation.assistant_fallback` | `true` | When retrieval is weak, answer from the assistant role prompt (identity/usage or "no relevant content") |
| `generation.assistant_task` | `assistant` | Prompt folder for the weak-retrieval fallback (`prompts/assistant/`) |
| `generation.weak_rerank_threshold` | `-2.0` | Retrieval counts as weak when the top rerank logit is below this |
| `retrieval.min_rerank_score` | `null` | Drop low-confidence retrieval (no chunks) when top rerank logit is below this |

When the queue is full, the API returns **`503`** with JSON `detail.error = "queue_full"` and headers:

- `Retry-After`
- `X-EE-Wiki-Queue-Active`
- `X-EE-Wiki-Queue-Waiting`
- `X-EE-Wiki-Queue-Max-Concurrent`
- `X-EE-Wiki-Queue-Max-Depth`
- `X-EE-Wiki-Queue-Capacity-Remaining`

`GET /health` includes the same counters under `queue` for monitoring.

## Retrieval context

| Setting | Default | Meaning |
|---------|---------|---------|
| `retrieval.top_k_final` | `8` | Chunk hits after rerank (before section merge) |
| `retrieval.expand_sections` | `true` | Merge sibling chunks from the same section for LLM context |
| `api.public_base_url` | `http://localhost:8080` | Base URL for clickable citation links in answers |

Chunking rules and the full index → query pipeline are in [data-flow.md](data-flow.md).

### Citations in responses

Each citation may include:

| Field | Meaning |
|-------|---------|
| `source_file` | Original raw path (provenance) |
| `chunk_id` | Indexed chunk identifier |
| `page` | Page number when applicable (schematics) |
| `excerpt` | Short preview of the retrieved text |
| `url` | Clickable download link to the **original** source document (`GET /v1/raw/...`) |
| `images` | Public URLs for images referenced in the chunk (`GET /v1/assets/...`) |

Inline markers like ``[1]`` stay as plain text in the assistant answer. Open WebUI renders them as clickable source chips when the chat completion response includes a parallel ``sources`` array (see below).


Request:

```json
{
  "query": "RMII 连接了哪些器件？",
  "product": "iphone",
  "project": "logan",
  "build": "p1",
  "document_type": null,
  "top_k": null,
  "task": "wiki"
}
```

`task` selects a prompt template from `prompts/{task}/default.md` (`wiki`, `debug`, `fa`, `design_review`). Default: `generation.default_task` in config.

Response:

```json
{
  "answer": "...",
  "insufficient_context": false,
  "citations": [
    {
      "source_file": "data/raw/acme/demo/p2/sch/board.pdf",
      "chunk_id": "board__p001",
      "page": 1,
      "excerpt": "...",
      "url": "http://localhost:8080/v1/raw/acme/demo/p2/sch/board.pdf",
      "images": [
        "http://localhost:8080/v1/assets/acme/demo/p2/sch/images/board_p001_crop_0.png"
      ]
    }
  ]
}
```

## `POST /v1/chat/completions`

OpenAI-compatible request with EE-Wiki metadata filters.

When `agents.enabled` is true (default), each chat turn first **locks TurnScope** (product/project/build) at the chat entry (ADR 0012 §6; carried across turns via a history marker), then an **authoritative connectivity gate** answers trace/net questions directly (or refuses), then an **FA-mode gate** routes FA-intent turns to `FaAgent` (works without a Radar id as an unbound FAQ). Remaining turns go to the **V4 Supervisor** (ADR 0008): clarify → keyword-scored specialists (`fa`/`hw`/`power`/`pcb`/`si`/`mfg`) → hybrid RAG. See [docs/usage/agents.md](../usage/agents.md). With `agents.enabled: false`, routing falls back to: TurnScope lock → connectivity gate → FA mode gate (`fa.enabled`) → hybrid RAG passthrough (no specialist routing).

Set `"stream": true` to receive Server-Sent Events: retrieval status updates during search, then token chunks in OpenAI `chat.completion.chunk` shape. Cancellation is supported when the client disconnects.

Non-streaming request example:

```json
{
  "model": "ee-wiki",
  "messages": [
    {"role": "user", "content": "board 的 COMM 接口有哪些信号？"}
  ],
  "project": "logan",
  "build": "p1"
}
```

Response shape:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "ee-wiki",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "citations": [],
  "sources": [
    {
      "document": ["..."],
      "metadata": [{"source": "http://localhost:8080/v1/raw/...", "name": "[1] manual.md"}],
      "source": {
        "name": "[1] manual.md",
        "url": "http://localhost:8080/v1/raw/..."
      }
    }
  ],
  "insufficient_context": false
}
```

## Responsibilities

| Layer | Owns |
|-------|------|
| Open WebUI | UI, sessions, user auth, model picker |
| EE-Wiki | Knowledge, retrieval, citations, engineering APIs |

## Response requirements

- Answers must include `citations[]` with `source_file`, `page`, `chunk_id`, `excerpt`, and when available `url` / `images` for clickable provenance.
- Insufficient context → `200` with explicit message and empty citations — not fabricated content.
- Request or LLM timeout → `504` with `detail.error = "request_timeout"` and message `请求超时，请重试`.

See [open-webui.md](../usage/open-webui.md) for frontend connection steps.

## MCP tools (V2)

Read-only engineering tools are exposed via **stdio** MCP (`scripts/mcp_serve.py`) for Cursor, Claude Desktop, and other local MCP clients. Open WebUI cannot attach stdio MCP directly (native support is Streamable HTTP only); use REST wrappers or host-side [mcpo](https://github.com/open-webui/mcpo) — see [open-webui.md](../usage/open-webui.md#mcp--engineering-tools-from-open-webui) and [mcp.md](../usage/mcp.md).

Install:

```bash
pip install -e ".[dev,ml,tools]"
```

Start:

```bash
python scripts/mcp_serve.py
```

| Tool | Purpose | REST equivalent |
|------|---------|-----------------|
| `search_component_tool` | Part number / designator lookup (`components.json`) | `GET /v1/components/search` |
| `search_debug_case_tool` | Debug / FA case lookup (`cases.json`) | `GET /v1/cases/search` |
| `query_power_tree_tool` | Heuristic power tree (`data/graph/` rails / supplies) | `GET /v1/power/tree` |
| `list_rules_tool` | List engineering rules (`config/rules/`) | `GET /v1/rules` |
| `evaluate_rules_tool` | Evaluate engineering rules (graph + cases) | `GET /v1/rules/evaluate` |
| `open_graph_node_tool` | Resolve/open one graph node | `GET /v1/graph/node` |
| `graph_neighbors_tool` | Graph neighbors within N hops | `GET /v1/graph/neighbors` |
| `graph_path_tool` | Shortest path between two nodes | `GET /v1/graph/path` |
| `graph_filter_tool` | Filter nodes by product/project/build scope | `GET /v1/graph/nodes` |
| `query_schematic_tool` | Hybrid retrieval scoped to `document_type=schematic` | `POST /v1/query` (filter schematic) |
| `search_datasheet_tool` | Hybrid retrieval scoped to `document_type=datasheet` | `POST /v1/query` (filter datasheet) |
| `engineering_search_tool` | General hybrid retrieval with optional `document_type` | `POST /v1/query` |
| `list_projects_tool` | Indexed product/project/build inventory | `GET /v1/projects` |
| `trace_net_tool` | Pins on a net from connectivity sidecars | `GET /v1/schematic/connectivity/net` |
| `connector_pins_tool` | Pin↔net for a designator | `GET /v1/schematic/connectivity/pins` |
| `module_nets_tool` | Module zone → nets | `GET /v1/schematic/connectivity/module-nets` |

All tools accept optional `project` and `build` filters and honor `retrieval.scope_inheritance` (graph tools honor `graph.scope_inheritance`). Results are JSON with `scope` labels (`build`, `common`, `global`). Graph tools require `python scripts/build_graph.py`. Connectivity tools require `*.connectivity.json` from schematic ingest (ADR 0009). `trace_net_tool` / `connector_pins_tool` enforce the authoritative-only gate: `authority: "insufficient"` (no `cad_netlist` evidence — BoardView `.brd` is advisory only) returns a refusal rather than a geometry/OCR guess.

Example Cursor MCP config:

```json
{
  "mcpServers": {
    "ee-wiki": {
      "command": "/path/to/EE-Wiki/.venv/bin/python",
      "args": ["/path/to/EE-Wiki/scripts/mcp_serve.py"]
    }
  }
}
```
