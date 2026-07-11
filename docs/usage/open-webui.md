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

### Inline schematic / document images

When `generation.inline_citation_images` is enabled (default: `true`), answers automatically append screenshots of referenced schematic pages and document figures below the answer text. Open WebUI renders these as inline images.

**Requirements:**

1. **`api.public_base_url` must be reachable from the user's browser** — not only from the Open WebUI server. If Open WebUI and EE-Wiki run on different machines, set this to a LAN-accessible address (e.g. `http://192.168.1.10:8080`). Image URLs use this base.
2. **Re-ingest schematic PDFs** after enabling `ingestion.schematic_pdf.save_page_images` (default: `true`) to generate full-page PNG renders:

```bash
python scripts/ingest.py --force data/raw/*/*/sch/
python scripts/index.py
```

**Config keys:**

| Key | Default | Purpose |
|-----|---------|---------|
| `ingestion.schematic_pdf.save_page_images` | `true` | Save full-page schematic renders as PNG during ingest |
| `generation.inline_citation_images` | `true` | Append referenced images after the answer |
| `generation.max_inline_images` | `4` | Cap on appended images per answer |
| `generation.show_elapsed_time` | `false` | When `true`, append phase timings: 检索 / 生成 (LLM prefill) / 首字 |

Images are served via `GET /v1/assets/{path}` from `data/processed/`.

## Create a chat model

1. In Open WebUI, add or select a model backed by the connection above
2. Use model name `ee-wiki` (or any name accepted by your Open WebUI version)
3. EE-Wiki reads the request `model` field but does not require a specific weight name

## Scope filters (project / build)

**Strongly recommended** for engineering questions. Answers distinguish `project` / `build` and knowledge layer (`build` vs project `common` vs `global`).

| Layer | Path | Role in answers |
|-------|------|-----------------|
| Build | `{project}/{build}/` | Default for pin, net, and BOM conclusions |
| Project common | `{project}/common/` | Project-wide guidance — label explicitly |
| Global | `global/` | Enterprise/industry background — not board wiring unless build agrees |

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

Without `project` / `build`, EE-Wiki can **infer scope from the question** when `generation.scope_inference` is enabled (default: `true`). Examples:

- `Logan p1 lcd的pin有哪些` → product `logan`, revision `p1`, build-layer retrieval
- `logan common 架构` → project-wide `common` knowledge for `logan`
- `global CH340` → enterprise `global` layer (not a product name)

`global` and `common` are **knowledge layers**, not product or revision names. API `project` / `build` fields still override inferred scope when provided.

When scope cannot be inferred, retrieval searches the **entire index**; answers should list findings **per scope** and recommend specifying scope for build-level conclusions.

## Troubleshooting

| Issue | Check |
|-------|-------|
| Connection refused | `python scripts/serve.py` running; firewall allows port `8080` |
| Empty or generic answers | Run `python scripts/query.py "..." --project logan --build p1` to verify retrieval |
| `models.llm_mlx_model is not configured` | Set `llm_mlx_model` (or `llm_transformers_model` if using transformers backend) in `config/default.yaml` |
| Slow first response | Enable `api.warmup_on_startup: true`; first load of embedding, reranker, and LLM can take minutes |
| Request hangs with no reply | Check server logs; tune `api.request_timeout_seconds` and `generation.llm_timeout_seconds` |
| Open WebUI stuck after first answer | Open WebUI sends **title/tag** background tasks to the same backend; EE-Wiki bypasses RAG for those prompts (``### Task:`` + ``<chat_history>``). Restart `serve.py` after upgrading if an old build ran full RAG on title generation (137k+ token prompts). Optionally disable **Settings → Interface → Chat title generation** in Open WebUI |
| Cancel in Open WebUI but server keeps running | Restart `serve.py`; chat uses cancellable streaming |
| Assistant questions cite datasheets | Ensure `generation.assistant_fallback: true`; tune `generation.weak_rerank_threshold` if weak retrieval still reaches the wiki prompt |
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
- [mcp.md](mcp.md) — V2 component lookup and MCP tools
- [api-overview.md](../architecture/api-overview.md) — endpoint contracts
