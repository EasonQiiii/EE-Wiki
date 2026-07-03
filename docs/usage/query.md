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

By default, `index.py` only re-chunks and re-embeds processed documents whose `source_mtime` / `source_size` changed since the last build (same fingerprint fields ingest uses). Unchanged documents reuse existing chunk rows and embeddings. Documents removed from `data/processed/` (for example after raw files were deleted and `scripts/ingest.py` ran orphan cleanup) are dropped from the index on the next incremental run; when no processed documents remain, the index bundle is cleared. Use `--force` for a full rebuild after chunker config changes or when you want to refresh every vector.

```bash
python scripts/index.py --force
```

### Incremental updates and deletions

| Event | `ingest.py` | `index.py` |
|-------|-------------|------------|
| New raw file | Ingests into `data/processed/` | Re-chunks and embeds on next run |
| Raw file changed | Re-ingests when `mtime` / size differ | Re-indexes when sidecar fingerprint differs |
| Raw file deleted | Removes processed `.md` + sidecar (directory/full-tree runs only) | Drops document from index; clears index if nothing remains |

After deleting raw files, always run `ingest.py` then `index.py` — see [ingest.md — Sync after deletions](ingest.md#sync-after-deletions).

On Apple Silicon, index embedding defaults to **CPU** (`indexing.embed_device: cpu` in `config/default.yaml`) to avoid PyTorch MPS errors such as `Invalid buffer size: 32.00 GiB`. Override with `EE_WIKI_EMBED_DEVICE=mps` if you prefer GPU embedding.

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

After `models.llm_mlx_model` (or `models.llm_transformers_model`) is configured, generate an answer with citations:

```bash
python scripts/ask.py "board 的 COMM 接口有哪些信号？" --project acme --build p2
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
