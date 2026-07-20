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
| `EE_WIKI_OPENAI_BASE_URL` | External LLM when `generation.llm_backend: openai` |
| `EE_WIKI_OPENAI_MODEL` | Model name on the inference server |
| `EE_WIKI_OPENAI_API_KEY` | Optional bearer token for the inference server |
| `EE_WIKI_INGEST_API_KEY` | Optional shared secret for `POST /v1/ingest` (and job poll) |

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

On **48 GB** memory the default 9B MLX LLM plus embed + rerank runs comfortably. Schematic ingest defaults to `ocr_only` (no VLM). If you set `fidelity_mode: vlm_plus_ocr`, prefer running `scripts/ingest.py` when `serve.py` is stopped — VLM load peaks memory briefly.

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

## Multi-user RAG (single Mac)

For several engineers querying at once, run the LLM in a **separate inference process** and point EE-Wiki at it via the OpenAI-compatible HTTP backend. See [ADR 0003](../adr/0003-external-llm-openai-compatible.md).

### 1. Install mlx-openai-server

Install into the **EE-Wiki venv** (not the Open WebUI venv — version pins conflict):

```bash
source .venv/bin/activate
pip install mlx-openai-server
```

Verify the CLI:

```bash
mlx-openai-server --help
```

### 2. Start inference (terminal 1)

```bash
export EE_WIKI_MODELS_DIR=/path/to/models
./scripts/start_mlx_openai_server.sh
```

Or manually (note: use the `launch` subcommand, not `python -m mlx_openai_server`):

```bash
mlx-openai-server launch \
  --model-type lm \
  --model-path "$EE_WIKI_MODELS_DIR/Qwen3-30B-A3B-Instruct-2507-MLX-4bit" \
  --served-model-name Qwen3-30B-A3B-Instruct-2507-MLX-4bit \
  --host 127.0.0.1 --port 8000 \
  --decode-concurrency 4 \
  --prompt-concurrency 2
```

On **48 GB** RAM, start with `--decode-concurrency 4`; reduce to `2` if you see Metal OOM. Monitor queue stats at `http://127.0.0.1:8000/v1/queue/stats` when available.

### 3. Configure EE-Wiki

In [`config/default.yaml`](../../config/default.yaml) (or via env vars):

```yaml
generation:
  llm_backend: openai
  openai_base_url: http://127.0.0.1:8000/v1
  openai_model: Qwen3-30B-A3B-Instruct-2507-MLX-4bit

api:
  concurrency:
    max_concurrent: 6
    max_queue_depth: 12
```

### 4. Start EE-Wiki API (terminal 2)

```bash
python scripts/serve.py
# optional: python scripts/serve.py --workers 2
```

Or use [`scripts/serve_with_llm.sh`](../../scripts/serve_with_llm.sh) to verify the inference server is up before starting EE-Wiki.

Open WebUI still connects to `http://<host>:8080/v1` — no frontend change.

**Notes:**

- `generation.llm_backend: mlx` remains the single-user default (`max_concurrent: 1`).
- Schematic/datasheet **ingest** (VLM) still runs via `scripts/ingest.py`; do not run heavy ingest while the inference server is under load.
- `query_prepare: merged` (default) combines query rewrite + task classification into one LLM call before retrieval.

## Operator workflow

```bash
# 1. Place documents under data/raw/{product}/{project}/{build}/{type}/

# 2. Ingest + index
python scripts/sync.py

# 3. Smoke test (retrieval only)
python scripts/query.py "test query" --product <product> --project <project> --build <build>

# 4. Smoke test (RAG + citations)
python scripts/ask.py "test question" --product <product> --project <project> --build <build> --json

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
- [ ] Scope inheritance: query `product=P, project=X, build=Y` finds `P/X/common/`, `P/common/`, and `global/` content
- [ ] Deletion sync: remove a raw file → `sync.py` → chunk gone from index
- [ ] Insufficient context: unrelated question returns explicit message, no fabrication
- [ ] `ask.py --json` returns `citations[]` with `source_file`, `chunk_id`, `excerpt`
- [ ] RAG answers label `product` / `project` / `build` and distinguish build vs project/product common vs global
- [ ] `serve.py` + Open WebUI: `[1]` markers link to processed documents
- [ ] `pytest` and `ruff check src tests` pass

## V2 acceptance checklist

After V2 metadata and tooling upgrades, additionally verify:

- [ ] Re-ingest `sch/` with `--force` → schematic sidecar includes `pages`; chunks have per-page `major_components`
- [ ] Re-ingest `datasheet/` PDFs → sidecar has `supply_voltage` / `pin_count` / `package` where applicable
- [ ] FA reports under `fa/` → `document_type=failure_analysis` and FA keywords in sidecar
- [ ] `data/indexes/components.json` exists after index; `GET /v1/components/search?q=U101` returns hits
- [ ] `python scripts/mcp_serve.py` starts; Cursor can call `search_component_tool` / `query_schematic_tool`
- [ ] `POST /v1/ingest` with `{"force":true}` completes (set `EE_WIKI_INGEST_API_KEY` on LAN)
- [ ] Mandatory eval: `python scripts/eval_rag.py --mandatory-only --fail-on-threshold`

See [mcp.md](mcp.md) for re-sync commands.

## Related docs

- [knowledge-authoring.md](knowledge-authoring.md) — write & place documents (spec for AI reformatting)
- [ingest.md](ingest.md) — raw → processed
- [index.md](index.md) — processed → indexes
- [query.md](query.md) — CLI retrieval and RAG
- [open-webui.md](open-webui.md) — frontend connection
- [mcp.md](mcp.md) — V2 tools (component lookup, MCP, HTTP ingest)
- [api-overview.md](../architecture/api-overview.md) — HTTP contracts
