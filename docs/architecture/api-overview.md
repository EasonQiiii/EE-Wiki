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
pip install -e ".[dev,ml,api]"
python scripts/serve.py
```

Default bind: `0.0.0.0:8080` (see `config/default.yaml` → `api`).

Set `api.warmup_on_startup: true` to preload the index, embedding model, reranker, and LLM when the server starts (recommended for Open WebUI; first startup may take several minutes).

## `POST /v1/query`

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
