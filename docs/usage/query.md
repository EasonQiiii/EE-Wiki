# Query Guide

How to run retrieval and RAG queries against EE-Wiki indexes.

## Prerequisites

```bash
cd /path/to/EE-Wiki
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

Build indexes first (see [ingest.md](ingest.md)):

```bash
python scripts/ingest.py
python scripts/index.py
```

Requires local models configured in `config/default.yaml`:

- `embedding_model` — dense recall (e.g. `bge-m3`)
- `reranker_model` — cross-encoder rerank (e.g. `bge-reranker-v2-m3`)

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

After `models.llm_model` is configured, generate an answer with citations:

```bash
python scripts/ask.py "Explorer 板的以太网接口是什么？" --project logan --build p1
```

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
  -d '{"query":"iPad manual","project":"logan","build":"p1"}'
```

See [open-webui.md](open-webui.md) for Open WebUI integration.

## Related docs

- [data-flow.md](../architecture/data-flow.md) — ingestion and query pipelines
- [api-overview.md](../architecture/api-overview.md) — REST endpoint contracts
