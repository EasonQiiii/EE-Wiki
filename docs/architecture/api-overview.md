# API Overview

EE-Wiki serves as the backend for Open WebUI. This document tracks the HTTP surface area.

**Status:** V1 — core query endpoints implemented.

## Implemented endpoints (V1)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness for deployment |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `POST` | `/v1/query` | Explicit RAG query with citation payload |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (retrieval + generation) |

## Planned endpoints (later)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/ingest` | Trigger document ingestion (admin) |

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

When the queue is full, the API returns **`503`** with JSON `detail.error = "queue_full"` and headers:

- `Retry-After`
- `X-EE-Wiki-Queue-Active`
- `X-EE-Wiki-Queue-Waiting`
- `X-EE-Wiki-Queue-Max-Concurrent`
- `X-EE-Wiki-Queue-Max-Depth`
- `X-EE-Wiki-Queue-Capacity-Remaining`

`GET /health` includes the same counters under `queue` for monitoring.


Request:

```json
{
  "query": "RMII 连接了哪些器件？",
  "project": "logan",
  "build": "p1",
  "document_type": null,
  "top_k": null
}
```

Response:

```json
{
  "answer": "...",
  "insufficient_context": false,
  "citations": [
    {
      "source_file": "data/raw/logan/p1/sch/Explorer STM32F4_V2.2_SCH.pdf",
      "chunk_id": "Explorer STM32F4_V2.2_SCH__p001",
      "page": 1,
      "excerpt": "..."
    }
  ]
}
```

## `POST /v1/chat/completions`

OpenAI-compatible request with EE-Wiki metadata filters:

```json
{
  "model": "ee-wiki",
  "messages": [
    {"role": "user", "content": "Explorer 板的以太网接口是什么？"}
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
  "insufficient_context": false
}
```

## Responsibilities

| Layer | Owns |
|-------|------|
| Open WebUI | UI, sessions, user auth, model picker |
| EE-Wiki | Knowledge, retrieval, citations, engineering APIs |

## Response requirements

- Answers must include `citations[]` with `source_file`, `page`, `chunk_id`, and excerpt when available.
- Insufficient context → `200` with explicit message and empty citations — not fabricated content.

See [open-webui.md](../usage/open-webui.md) for frontend connection steps.

Future: MCP tools documented in README.md (`search_component`, `query_schematic`, etc.) will map to `src/ee_wiki/tools/` in V2+.
