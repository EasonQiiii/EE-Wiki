# API Overview

EE-Wiki serves as the backend for Open WebUI. This document tracks the HTTP surface area.

**Status:** V1 — core query endpoints implemented.

## Implemented endpoints (V1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness for deployment |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `GET` | `/v1/sources/{path}` | Processed Markdown/text document for citation links |
| `GET` | `/v1/assets/{path}` | Image or asset under `data/processed/` |
| `POST` | `/v1/query` | Explicit RAG query with citation payload |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (retrieval + generation); set `"stream": true` for SSE |

## Planned endpoints (V2+)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/ingest` | Trigger document ingestion (admin); V1 uses `scripts/ingest.py` / `scripts/sync.py` |

## Start the server

```bash
pip install -e ".[dev,ml,mlx,api]"
python scripts/serve.py
```

RAG/chat uses `generation.llm_backend` (default `mlx`) with `models.llm_mlx_model` or `models.llm_transformers_model` depending on backend. Schematic PDF ingest still uses `models.visual_model` (Qwen3-VL via transformers).

Default bind: `0.0.0.0:8080` (see `config/default.yaml` → `api`).

Set `api.warmup_on_startup: true` to preload the index, embedding model, reranker, and LLM when the server starts (recommended for Open WebUI; first startup may take several minutes).

## Concurrency and queue limits

LAN deployments use a bounded queue on `/v1/query` and `/v1/chat/completions`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `api.concurrency.max_concurrent` | `1` | Active RAG requests |
| `api.concurrency.max_queue_depth` | `8` | Additional requests allowed to wait |
| `api.concurrency.retry_after_seconds` | `15` | `Retry-After` when queue is full |
| `api.request_timeout_seconds` | `300` | Whole RAG request wall-clock cap (`504` when exceeded; `null` or `0` disables) |

Generation timeouts:

| Setting | Default | Meaning |
|---------|---------|---------|
| `generation.max_new_tokens` | `2048` | Maximum LLM output tokens per answer |
| `generation.llm_timeout_seconds` | `180` | LLM generation cap (`504` via request handler; `null` or `0` disables) |
| `generation.intent_routing` | `true` | Classify assistant-meta vs engineering before retrieval |
| `generation.assistant_task` | `assistant` | Prompt folder for assistant-meta answers (`prompts/assistant/`) |
| `generation.intent_similarity_margin` | `0.02` | Embedding margin for intent routing (see `config/intent_exemplars.yaml`) |
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

Future: MCP tools documented in README.md (`search_component`, `query_schematic`, etc.) will map to `src/ee_wiki/tools/` in V2+.
