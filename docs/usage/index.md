# Index Guide

How to run `scripts/index.py` and `scripts/sync.py` — build hybrid retrieval indexes from `data/processed/`.

## Prerequisites

```bash
cd /path/to/EE-Wiki
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

Ingest raw documents first (see [ingest.md](ingest.md)):

```bash
python scripts/ingest.py
python scripts/index.py
```

Or run both in one command:

```bash
python scripts/sync.py
```

Requires local models configured in `config/default.yaml`:

- `embedding_model` — dense recall (e.g. `bge-m3`)
- `reranker_model` — cross-encoder rerank at query time (e.g. `bge-reranker-v2-m3`)

## Basic command

From the repository root:

```bash
python scripts/index.py
python scripts/sync.py    # ingest + index in one command
```

This reads all processed documents under `data/processed/`, chunks them, embeds new or changed documents, and writes a hybrid index bundle to `data/indexes/`:

- `manifest.json` — build metadata and per-document fingerprints
- `chunks.jsonl` — chunk text and citation metadata
- `embeddings.npz` — dense vectors aligned with chunks
- `bm25_corpus.json` — tokenized corpus for sparse recall

## Incremental index (default)

By default, `index.py` compares each processed document's `source_mtime` and `source_size` (from the `.meta.json` sidecar) to the last build's `manifest.json` fingerprints:

| Situation | Behavior |
|-----------|----------|
| New processed document | Chunk and embed |
| Changed fingerprint | Re-chunk and re-embed |
| Unchanged fingerprint | Reuse existing chunk rows and embeddings |
| Removed from `data/processed/` | Drop from index on next run |
| No processed documents remain | Clear entire index bundle |

Same fingerprint fields as incremental ingest — see [ingest.md — Incremental ingest](ingest.md#incremental-ingest).

### Incremental updates and deletions

| Event | `ingest.py` | `index.py` |
|-------|-------------|------------|
| New raw file | Ingests into `data/processed/` | Re-chunks and embeds on next run |
| Raw file changed | Re-ingests when `mtime` / size differ | Re-indexes when sidecar fingerprint differs |
| Raw file deleted | Removes processed `.md` + sidecar (directory/full-tree runs only) | Drops document from index; clears index if nothing remains |

After deleting raw files, run `python scripts/sync.py` or ingest then index — see [ingest.md — Sync after deletions](ingest.md#sync-after-deletions).

## Force rebuild

```bash
python scripts/index.py --force
```

Use `--force` after chunker config changes (`config/default.yaml` → `chunking.*`) or when you want to refresh every embedding vector. Chunk boundaries are fixed at index time; retrieval does not re-chunk.

## Device settings

On Apple Silicon, index embedding defaults to **CPU** (`indexing.embed_device: cpu` in `config/default.yaml`) to avoid PyTorch MPS errors such as `Invalid buffer size: 32.00 GiB`. Override with `EE_WIKI_EMBED_DEVICE=mps` if you prefer GPU embedding.

| Setting | Default | Meaning |
|---------|---------|---------|
| `indexing.embed_device` | `cpu` | Torch device for sentence-transformers during index build |
| `indexing.embed_batch_size` | `8` | Embedding batch size |

## CLI summary

```bash
# stderr summary after each run:
# Indexed: 2 document(s), skipped (unchanged): 5, removed (processed deleted): 0 → 42 chunk(s) in data/indexes

# stdout prints manifest built_at timestamp when index was written
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| `No processed documents found` | Run `python scripts/ingest.py` first |
| `models.embedding_model is not configured` | Set model path in `config/default.yaml` or `EE_WIKI_MODELS_DIR` |
| MPS embedding error during index | Set `indexing.embed_device: cpu` or `EE_WIKI_EMBED_DEVICE=cpu` |
| Deleted docs still appear in query | Run `python scripts/index.py` after ingest cleanup |
| Stale chunks after chunker change | Run `python scripts/index.py --force` |

## Related docs

- [ingest.md](ingest.md) — raw → processed pipeline
- [query.md](query.md) — retrieval and RAG queries
- [data-flow.md](../architecture/data-flow.md) — chunking and index pipeline
