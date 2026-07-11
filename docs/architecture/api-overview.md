# API Overview

EE-Wiki serves as the backend for Open WebUI. This document tracks the HTTP surface area.

**Status:** V2 — core query + component lookup + ingest admin + MCP tools.

## Scope filters (`project` / `build`)

Strongly recommended for engineering questions.

| Field | Meaning |
|-------|---------|
| `project` | Product/program (e.g. `logan`) |
| `build` | Hardware revision (e.g. `p1`) or `common` for project-wide-only queries |

When both are set with `retrieval.scope_inheritance: true` (default), search expands to `{project}/{build}` → `{project}/common` → `global`. Answers must label conclusions by scope (`build`, project `common`, `global`). Omitting both fields searches the entire index.

## Implemented endpoints (V1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness for deployment |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `GET` | `/v1/sources/{path}` | Processed Markdown/text document for citation links |
| `GET` | `/v1/assets/{path}` | Image or asset under `data/processed/` |
| `POST` | `/v1/query` | Explicit RAG query with citation payload |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (retrieval + generation); set `"stream": true` for SSE |

## Implemented endpoints (V2)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/components/search` | Part number / designator lookup against `data/indexes/components.json` |
| `POST` | `/v1/ingest` | Trigger document ingestion and optional index build (admin) |

Query params for `GET /v1/components/search`: `q` (required), optional `project`, `build`, `limit` (default 20).

### `POST /v1/ingest`

Admin endpoint to run the same pipeline as `scripts/sync.py` (ingest raw → processed, then build/update indexes). Orchestrates existing `ingest_path` and `build_index_from_processed` — no parsing logic in the route.

Request (all fields optional):

```json
{
  "path": "logan/p1/fa/rma-report.md",
  "paths": null,
  "project": "logan",
  "build": "p1",
  "force": false,
  "ingest_only": false,
  "index_only": false
}
```

| Field | Meaning |
|-------|---------|
| `path` | Single file or directory under `data/raw/` (relative, `data/raw/...`, or absolute under raw dir) |
| `paths` | List of paths (mutually exclusive with `path`) |
| `project` / `build` | When no path given, scope to `data/raw/{project}/` or `data/raw/{project}/{build}/` |
| `force` | Re-ingest and rebuild even when fingerprints match |
| `ingest_only` | Skip index build (like `scripts/sync.py --ingest-only`) |
| `index_only` | Skip ingest (like `scripts/sync.py --index-only`) |

When all path filters are omitted, the entire `data/raw/` tree is processed.

Response:

```json
{
  "ingested": 2,
  "skipped": 5,
  "removed": 0,
  "ingested_files": ["data/processed/logan/p1/fa/rma-report.md"],
  "removed_files": [],
  "indexed_documents": 2,
  "skipped_documents": 5,
  "removed_documents": 0,
  "chunk_count": 42
}
```

Index fields (`indexed_documents`, `skipped_documents`, `removed_documents`, `chunk_count`) are `null` when `ingest_only: true`. Ingest counts are zero when `index_only: true`.

Errors: `400` for invalid paths or conflicting flags; `404` when the target path does not exist; `500` when index build fails (e.g. no processed documents on first run).

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
| `retrieval.top_k_final` | `5` | Chunk hits after rerank (before section merge) |
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
| `url` | Clickable link to the processed document (`GET /v1/sources/...`) |
| `images` | Public URLs for images referenced in the chunk (`GET /v1/assets/...`) |

Inline markers like ``[1]`` stay as plain text in the assistant answer. Open WebUI renders them as clickable source chips when the chat completion response includes a parallel ``sources`` array (see below).


Request:

```json
{
  "query": "RMII 连接了哪些器件？",
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
      "source_file": "data/raw/acme/p2/sch/board.pdf",
      "chunk_id": "board__p001",
      "page": 1,
      "excerpt": "...",
      "url": "http://localhost:8080/v1/sources/acme/p2/sch/board.md#p001",
      "images": [
        "http://localhost:8080/v1/assets/acme/p2/sch/images/board_p001_crop_0.png"
      ]
    }
  ]
}
```

## `POST /v1/chat/completions`

OpenAI-compatible request with EE-Wiki metadata filters.

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
      "metadata": [{"source": "http://localhost:8080/v1/sources/...", "name": "[1] manual.md"}],
      "source": {
        "name": "[1] manual.md",
        "url": "http://localhost:8080/v1/sources/..."
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

Read-only engineering tools are exposed via stdio MCP for Cursor, Claude Desktop, and other MCP clients.

Install:

```bash
pip install -e ".[dev,ml,tools]"
```

Start:

```bash
python scripts/mcp_serve.py
```

| Tool | Purpose |
|------|---------|
| `search_component_tool` | Part number / designator lookup (`components.json`) |
| `query_schematic_tool` | Hybrid retrieval scoped to `document_type=schematic` |
| `search_datasheet_tool` | Hybrid retrieval scoped to `document_type=datasheet` |
| `engineering_search_tool` | General hybrid retrieval with optional `document_type` |

All tools accept optional `project` and `build` filters and honor `retrieval.scope_inheritance`. Results are JSON with `scope` labels (`build`, `common`, `global`).

Example Cursor MCP config:

```json
{
  "mcpServers": {
    "ee-wiki": {
      "command": "python",
      "args": ["/path/to/EE-Wiki/scripts/mcp_serve.py"]
    }
  }
}
```
