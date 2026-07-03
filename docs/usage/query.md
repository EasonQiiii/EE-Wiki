# Query Guide

How to run retrieval and RAG queries against EE-Wiki indexes.

## Prerequisites

```bash
cd /path/to/EE-Wiki
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

Build indexes first — see [index.md](index.md):

```bash
python scripts/sync.py
```

Or separately:

```bash
python scripts/ingest.py
python scripts/index.py
```

Requires local models configured in `config/default.yaml`:

- `embedding_model` — dense recall (e.g. `bge-m3`)
- `reranker_model` — cross-encoder rerank (e.g. `bge-reranker-v2-m3`)
- `llm_mlx_model` or `llm_transformers_model` — for RAG answers (see below)

## Project / build scope (recommended)

| Layer | Path | Use in answers |
|-------|------|----------------|
| **Build** | `{project}/{build}/` | Board-level truth — default for engineering conclusions |
| **Project common** | `{project}/common/` | That project's cross-build knowledge — label explicitly |
| **Global** | `global/` | All-project tools, industry practices, generic datasheets — background only |

Always pass `--project` and `--build` when you know the target hardware revision. Without them, retrieval searches the **full index**; RAG answers should still **label each conclusion by scope**.

## Retrieval only (`scripts/query.py`)

Run hybrid retrieval without calling an LLM:

```bash
python scripts/query.py "RMII 接口" --project logan --build p1
python scripts/query.py "iPad 充电" --project logan --build p1 --top-k 5
python scripts/query.py "ETH_MDIO" --project logan --build p1 --document-type schematic
```

Output includes for each chunk:

- `chunk_id`
- `source_file`
- `page`
- `excerpt`
- content preview (first 200 characters)

## End-to-end RAG (`scripts/ask.py`)

After `models.llm_mlx_model` (or `models.llm_transformers_model`) is configured, generate an answer with citations:

```bash
python scripts/ask.py "board 的 COMM 接口有哪些信号？" --project acme --build p2
python scripts/ask.py "VBAT 连接了哪些器件？" --project logan --build p1 --task debug
```

Use `--task` to select a prompt template from `prompts/{task}/default.md`:

| Task | Folder | Purpose |
|------|--------|---------|
| `wiki` (default) | `prompts/wiki/` | General engineering Q&A |
| `debug` | `prompts/debug/` | Hardware debug |
| `fa` | `prompts/fa/` | Failure analysis |
| `design_review` | `prompts/design_review/` | Design review |

Default task is set in `config/default.yaml` → `generation.default_task`.

## HTTP API

Start the API server:

```bash
pip install -e ".[dev,ml,api]"
python scripts/serve.py
```

Example query:

```bash
curl -X POST http://localhost:8080/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"iPad manual","project":"logan","build":"p1","task":"wiki"}'
```

See [open-webui.md](open-webui.md) for Open WebUI integration.

## Related docs

- [index.md](index.md) — building and updating indexes
- [ingest.md](ingest.md) — raw → processed pipeline
- [data-flow.md](../architecture/data-flow.md) — ingestion and query pipelines
- [api-overview.md](../architecture/api-overview.md) — REST endpoint contracts
