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
| Slow first response | First request loads embedding, reranker, and LLM weights |

## Related docs

- [query.md](query.md) — CLI retrieval and RAG usage
- [api-overview.md](../architecture/api-overview.md) — endpoint contracts
