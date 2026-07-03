# 0002. V1 Runtime Stack

Date: 2026-07-03
Status: accepted

## Context

EE-Wiki V1 must run fully offline on enterprise hardware with local models and on-disk artifacts. AGENTS.md §16 lists several open technology choices (vector database, embedding/reranker IDs, LLM runtime, chunking). Chunking is already decided in [0001-chunking-strategy.md](0001-chunking-strategy.md).

We need a single accepted baseline so implementation and operations do not re-litigate the same stack on every feature.

## Decision

### 1. Index and sparse storage (V1)

Use a **flat on-disk hybrid index bundle** under `data/indexes/`:

| File | Role |
|------|------|
| `manifest.json` | Build metadata and per-document fingerprints |
| `chunks.jsonl` | Chunk text + citation metadata |
| `embeddings.npz` | Dense vectors aligned with chunks |
| `bm25_corpus.json` | Tokenized corpus for sparse recall |

Implementation: [`src/ee_wiki/knowledge/indexer/store.py`](../../src/ee_wiki/knowledge/indexer/store.py).

No external vector database (Qdrant, pgvector, Milvus, …) in V1.

### 2. Embedding and reranker

- **Library**: `sentence-transformers` for indexing; cross-encoder reranker loaded in retrieval
- **Model paths**: configured in `config/default.yaml` → `models.embedding_model`, `models.reranker_model`
- **Defaults in repo config**: `bge-m3`, `bge-reranker-v2-m3` (paths resolved under `models.base_dir`)

Model IDs are configuration, not hardcoded in `src/`.

### 3. Local LLM runtime (V1)

- **Default backend**: MLX (`generation.llm_backend: mlx`) on Apple Silicon via `generation/llm/mlx.py`
- **Alternative**: Hugging Face Transformers via `generation/llm/local.py` when `generation.llm_backend: transformers`
- Model paths: `models.llm_mlx_model`, `models.llm_transformers_model`

Ollama, vLLM, and llama.cpp remain future options; adopting one requires a new ADR.

### 4. Chunking

Deferred to [0001-chunking-strategy.md](0001-chunking-strategy.md). Re-index with `python scripts/index.py --force` after chunker changes.

### 5. Incremental ingest and index

- **Ingest**: fingerprint skip + orphan cleanup when raw files are removed ([`ingestion/sync.py`](../../src/ee_wiki/ingestion/sync.py), [`ingestion/cleanup.py`](../../src/ee_wiki/ingestion/cleanup.py))
- **Index**: fingerprint reuse + removal sync ([`knowledge/indexer/sync.py`](../../src/ee_wiki/knowledge/indexer/sync.py))
- **Operator CLI**: `scripts/sync.py` runs ingest then index

## Consequences

### Positive

- Zero network dependency at query time beyond the local LAN API
- Simple backup: copy `data/processed/` and `data/indexes/`
- Clear module boundaries: indexer writes, retrieval reads, generator never touches disk indexes directly

### Negative / limits

- Full index load into process memory at retrieval time; very large corpora may need sharding or an external vector store in V2+
- Embedding/reranker model swaps require config updates and re-index or query-time reload
- MLX-first LLM path is optimized for Apple Silicon; other platforms should use `transformers` backend

### Follow-ups (not V1)

- ADR 0003+ if migrating to Qdrant/pgvector or adding Ollama/vLLM
- `protocols/` abstractions before a second index or LLM backend implementation
