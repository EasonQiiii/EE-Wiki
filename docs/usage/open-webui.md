# Open WebUI Integration

Connect Open WebUI to EE-Wiki as a custom OpenAI-compatible backend.

## Prerequisites

1. EE-Wiki indexes are built (`python scripts/ingest.py` and `python scripts/index.py`)
2. Local models are configured in `config/default.yaml`:
   - `embedding_model`
   - `reranker_model`
   - `llm_model` (uncomment and set your local model directory name)
3. API dependencies installed:

```bash
pip install -e ".[dev,ml,api]"
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
| `models.llm_model is not configured` | Uncomment/set `llm_model` in `config/default.yaml` |
| Slow first response | Enable `api.warmup_on_startup: true`; first load of embedding, reranker, and LLM can take minutes |
| Open WebUI shows no output | Wait for server warmup; first LLM load can take 1–3 min on Mac. Check `curl http://localhost:8080/health` first |
| `503` LLM load error | NVFP4 models (e.g. `Qwen3.6-27B-NVFP4`) are not supported; use `Qwen3-VL-4B-Instruct` or another standard HF folder |
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
