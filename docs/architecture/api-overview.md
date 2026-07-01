# API Overview

EE-Wiki serves as the backend for Open WebUI. This document tracks the HTTP surface area.

**Status:** V0 — endpoints are planned, not implemented.

## Planned endpoints (V1)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (orchestrates retrieval + generation) |
| `POST` | `/v1/query` | Explicit RAG query with citation payload |
| `POST` | `/v1/ingest` | Trigger document ingestion (admin) |
| `GET` | `/health` | Liveness for deployment |

## Responsibilities

| Layer | Owns |
|-------|------|
| Open WebUI | UI, sessions, user auth, model picker |
| EE-Wiki | Knowledge, retrieval, citations, engineering APIs |

## Response requirements

- Answers must include `citations[]` with `source_file`, `page`, `chunk_id`, and excerpt when available.
- Insufficient context → `200` with explicit message and empty or partial citations — not fabricated content.

Future: MCP tools documented in README.md (`search_component`, `query_schematic`, etc.) will map to `src/ee_wiki/tools/` in V2+.
