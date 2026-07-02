# Open WebUI Integration

Connect Open WebUI to EE-Wiki as a custom OpenAI-compatible backend.

## Prerequisites

1. EE-Wiki indexes are built (`python scripts/ingest.py` and `python scripts/index.py`)
2. Local models are configured in `config/default.yaml`:
   - `embedding_model`
   - `reranker_model`
   - `llm_mlx_model` — MLX 4-bit weights for RAG/chat when `generation.llm_backend: mlx`
   - `llm_transformers_model` — Hugging Face weights when `generation.llm_backend: transformers`
   - `visual_model` — Qwen3-VL for schematic PDF ingest only
3. API dependencies installed:

```bash
pip install -e ".[dev,ml,mlx,api]"
```

## Start EE-Wiki API

```bash
python scripts/serve.py
```

Verify:

```bash
curl http://localhost:8080/health
```

## Configure Open WebUI

1. Open **Settings → Connections** (or **Admin → External Connections** depending on version)
2. Add an **OpenAI API** connection
3. Set:
   - **Base URL**: `http://<ee-wiki-host>:8080/v1`
   - **API Key**: any placeholder (V1 does not enforce auth)
4. Save and enable the connection

Set `api.public_base_url` in `config/default.yaml` to the URL Open WebUI uses to reach EE-Wiki (e.g. `http://192.168.1.10:8080`). Citation links and images in answers use this base URL.

### Citation links `[1]` `[2]`

Answers cite context blocks with plain `[1]` markers in the assistant text. Open WebUI turns those into clickable source chips when EE-Wiki also returns a parallel `sources` array on the chat completion response.

- Set `public_base_url` to a browser-reachable host when Open WebUI is not on the same machine (citation URLs use this base).
- Click a `[1]` marker or the **N Sources** chip below the answer to open the processed document.
- EE-Wiki also returns structured `citations[]` for API and CLI consumers.

## Create a chat model

1. In Open WebUI, add or select a model backed by the connection above
2. Use model name `ee-wiki` (or any name accepted by your Open WebUI version)
3. EE-Wiki reads the request `model` field but does not require a specific weight name

## Scope filters (project / build)

V1 passes retrieval scope through extra JSON fields on chat requests:

```json
{
  "model": "ee-wiki",
  "messages": [{"role": "user", "content": "RMII 接口说明"}],
  "project": "logan",
  "build": "p1"
}
```

If your Open WebUI build cannot send custom fields on chat requests, use `POST /v1/query` directly or the CLI:

```bash
python scripts/ask.py "RMII 接口说明" --project logan --build p1
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| Connection refused | `python scripts/serve.py` running; firewall allows port `8080` |
| Empty or generic answers | Run `python scripts/query.py "..." --project logan --build p1` to verify retrieval |
| `models.llm_mlx_model is not configured` | Set `llm_mlx_model` (or `llm_transformers_model` if using transformers backend) in `config/default.yaml` |
| Slow first response | Enable `api.warmup_on_startup: true`; first load of embedding, reranker, and LLM can take minutes |
| Open WebUI shows no output | Wait for server warmup; first LLM load can take 1–3 min on Mac. Check `curl http://localhost:8080/health` first |
| `503` queue full | Server busy; retry after `Retry-After` seconds. Check `GET /health` → `queue`. Increase `api.concurrency.max_queue_depth` if needed |
| `503` LLM load error | Ensure MLX weights exist under `models.base_dir`; run `pip install -e '.[mlx]'` |
| `404` on chat | Base URL must include `/v1`, e.g. `http://localhost:8080/v1` |

### Why embedding / reranker load at query time

Hybrid RAG uses models at two stages:

| Stage | When | Models |
|-------|------|--------|
| **Indexing** (`scripts/index.py`) | Offline, once per index build | `bge-m3` embeds document chunks into `data/indexes/` |
| **Query** (`/v1/chat/completions`) | Every question | `bge-m3` embeds the user query; `bge-reranker-v2-m3` reranks retrieved candidates |

The index stores chunk embeddings only. Query-time embedding and reranking are required for hybrid retrieval — they are not repeated indexing work.

## Related docs

- [query.md](query.md) — CLI retrieval and RAG usage
- [api-overview.md](../architecture/api-overview.md) — endpoint contracts
