# Local Setup (Apple Silicon)

Operator guide for running EE-Wiki V1 on a single Mac (tested profile: **M5 Pro, 48 GB** unified memory).

## Prerequisites

### Python and package

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ml,mlx,api]"
```

### Environment variables

Copy [`.env.example`](../../.env.example) and **export** variables in your shell (the repo does not auto-load `.env`):

```bash
export EE_WIKI_DATA_DIR=./data
export EE_WIKI_MODELS_DIR=/path/to/models
```

Optional:

| Variable | Purpose |
|----------|---------|
| `EE_WIKI_TESSDATA_DIR` | Tesseract data for prose PDF OCR |
| `EE_WIKI_EMBED_DEVICE` | `cpu` (default) or `mps` for `scripts/index.py` |
| `EE_WIKI_LIBREOFFICE_PATH` | Legacy `.doc` ingest via LibreOffice |

### System tools

| Tool | When needed |
|------|-------------|
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Scanned or image-only PDFs (`ingestion.prose_pdf`) |
| [LibreOffice](https://www.libreoffice.org/) | Legacy `.doc` files |

### Model weights

Place models under `EE_WIKI_MODELS_DIR`. Names match [`config/default.yaml`](../../config/default.yaml) → `models.*`:

| Config key | Default name | Used by |
|------------|--------------|---------|
| `embedding_model` | `bge-m3` | `scripts/index.py`, query-time embed |
| `reranker_model` | `bge-reranker-v2-m3` | Query-time rerank |
| `llm_mlx_model` | `Qwen3.5-9B-MLX-4bit` | RAG / chat (`generation.llm_backend: mlx`) |
| `visual_model` | `Qwen3-VL-4B-Instruct` | Schematic PDF ingest only |

On **48 GB** memory the default 9B MLX LLM plus embed + rerank runs comfortably. For schematic ingest, prefer running `scripts/ingest.py` when `serve.py` is stopped — VLM load peaks memory briefly.

## Recommended config (48 GB)

Default [`config/default.yaml`](../../config/default.yaml) works without downgrade:

| Setting | Value | Notes |
|---------|-------|-------|
| `generation.llm_backend` | `mlx` | Apple Silicon |
| `models.llm_mlx_model` | `Qwen3.5-9B-MLX-4bit` | Default |
| `indexing.embed_device` | `cpu` | Avoids known MPS embedding bugs; optional `mps` for faster index |
| `api.warmup_on_startup` | `true` | Preloads index + models; first start ~1–3 min |
| `api.concurrency.max_concurrent` | `1` | Single MLX LLM slot |

API bind: `config/default.yaml` → `api.host` / `api.port` (default `0.0.0.0:8080`), or:

```bash
python scripts/serve.py --host 0.0.0.0 --port 8080
```

Set `api.public_base_url` to the URL your browser uses for citation links (e.g. `http://192.168.1.10:8080` when Open WebUI is on another machine).

## Operator workflow

```bash
# 1. Place documents under data/raw/{project}/{build}/{type}/

# 2. Ingest + index
python scripts/sync.py

# 3. Smoke test (retrieval only)
python scripts/query.py "test query" --project <project> --build <build>

# 4. Smoke test (RAG + citations)
python scripts/ask.py "test question" --project <project> --build <build> --json

# 5. API server
python scripts/serve.py
curl http://localhost:8080/health
```

See [ingest.md](ingest.md), [index.md](index.md), [query.md](query.md), [open-webui.md](open-webui.md) for detail.

### Ongoing operations

| Event | Action |
|-------|--------|
| New or changed raw files | `python scripts/sync.py` |
| Deleted raw files | Directory or full-tree `ingest.py` / `sync.py`, then index |
| Chunker config change | `python scripts/index.py --force` |
| Scheduled refresh | `cron` entry for `sync.py` |

### Backup

Copy `data/processed/` and `data/indexes/` together (see [ADR 0002](../adr/0002-v1-runtime-stack.md)).

## V1 acceptance checklist

Run on real engineering documents before declaring V1 complete:

- [ ] `sync.py` completes without errors on your raw tree
- [ ] Engineering note (`note/`): headings chunk correctly; procedures stay intact
- [ ] Prose PDF (`sop/` or `datasheet/`): text or OCR content searchable
- [ ] Schematic PDF (`sch/`): page-level chunks; citations include `page` and image URLs
- [ ] Scope inheritance: query `project=X, build=Y` finds `X/common/` and `global/` content
- [ ] Deletion sync: remove a raw file → `sync.py` → chunk gone from index
- [ ] Insufficient context: unrelated question returns explicit message, no fabrication
- [ ] `ask.py --json` returns `citations[]` with `source_file`, `chunk_id`, `excerpt`
- [ ] RAG answers label `project` / `build` and distinguish build vs project common vs global
- [ ] `serve.py` + Open WebUI: `[1]` markers link to processed documents
- [ ] `pytest` and `ruff check src tests` pass

## Related docs

- [knowledge-authoring.md](knowledge-authoring.md) — write & place documents (spec for AI reformatting)
- [ingest.md](ingest.md) — raw → processed
- [index.md](index.md) — processed → indexes
- [query.md](query.md) — CLI retrieval and RAG
- [open-webui.md](open-webui.md) — frontend connection
- [api-overview.md](../architecture/api-overview.md) — HTTP contracts
