# 0003. External OpenAI-Compatible LLM

Date: 2026-07-06
Status: accepted

## Context

ADR [0002](0002-v1-runtime-stack.md) chose in-process MLX (`generation.llm_backend: mlx`) as the default RAG LLM on Apple Silicon. That path shares one GPU stream per process and forces `api.concurrency.max_concurrent: 1`, which blocks multi-user LAN deployments.

Operators need several engineers to query the same EE-Wiki instance concurrently without losing RAG (retrieval, citations, `project` / `build` scope). A separate inference process with request batching is the pragmatic fix on a single Mac.

## Decision

### 1. New LLM backend: `openai`

Add `generation.llm_backend: openai` that calls a **local** OpenAI-compatible HTTP API:

- Implementation: [`src/ee_wiki/generation/llm/openai_http.py`](../../src/ee_wiki/generation/llm/openai_http.py)
- Endpoint: `POST {openai_base_url}/chat/completions`
- EE-Wiki sends the fully rendered RAG prompt as a single `user` message
- Streaming via SSE (`stream: true`) for chat responses

Configuration (`config/default.yaml` → `generation`):

| Key | Purpose |
|-----|---------|
| `openai_base_url` | e.g. `http://127.0.0.1:8000/v1` |
| `openai_model` | Model name on the inference server |
| `openai_api_key` | Optional; placeholder for V1 (not enforced) |

Environment overrides: `EE_WIKI_OPENAI_BASE_URL`, `EE_WIKI_OPENAI_MODEL`, `EE_WIKI_OPENAI_API_KEY`.

### 2. First target runtime: mlx-openai-server

On Apple Silicon, run [mlx-openai-server](https://pypi.org/project/mlx-openai-server/) as a separate process:

```bash
mlx-openai-server launch --model-type lm --model-path ... --decode-concurrency 4
```

See [`scripts/start_mlx_openai_server.sh`](../../scripts/start_mlx_openai_server.sh). EE-Wiki does **not** load MLX LLM weights when `llm_backend: openai`.

### 3. Concurrency

- **Only `mlx` in-process** remains capped at `max_concurrent: 1`
- `openai` and `transformers` use the configured `api.concurrency.max_concurrent`
- Recommended single-host profile (48 GB + ~30B): `max_concurrent: 6`, `max_queue_depth: 12`, mlx-openai-server `--decode-concurrency 4`

### 4. Preserved backends

| Backend | Role |
|---------|------|
| `mlx` | Single-user / CLI / fallback when no external server |
| `transformers` | Non-Apple or HF weights |
| `openai` | Multi-user LAN RAG via local HTTP inference |

Ingest VLM (`models.visual_model`) remains in-process transformers; unrelated to chat LLM backend.

### 5. Offline-first

`openai_base_url` must point to an on-LAN host (default `127.0.0.1`). No cloud API is required or configured by default.

## Consequences

### Positive

- Multiple concurrent RAG requests without MLX process deadlock
- EE-Wiki API stays stateless; LLM memory isolated in inference process
- Open WebUI integration unchanged (`/v1/chat/completions` on EE-Wiki)

### Negative / limits

- Two processes to operate (inference server + EE-Wiki API)
- Retrieval (embed + rerank) still runs in EE-Wiki; very high concurrency may need more API workers or a future retrieval service
- Streaming cancel depends on closing the HTTP response; coarser than in-process MLX

### Follow-ups

- ADR 0004+ for external vector DB if index size demands it
- Optional dedicated retrieval microservice when embed/rerank becomes the bottleneck
- Dual-machine deployment (LLM host + API host) using the same `openai` backend
