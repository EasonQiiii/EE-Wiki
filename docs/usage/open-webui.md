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

## Scope filters (product / project / build)

**Strongly recommended** for engineering questions. Answers distinguish `product` / `project` / `build` and knowledge layer (`build` vs project/product `common` vs `global`).

| Layer | Path | Role in answers |
|-------|------|-----------------|
| Build | `{product}/{project}/{build}/` | Default for pin, net, and BOM conclusions |
| Project common | `{product}/{project}/common/` | Project-wide guidance — label explicitly |
| Product common | `{product}/common/` | Product-wide guidance — label explicitly |
| Global | `global/` | Enterprise/industry background — not board wiring unless build agrees |

Passes retrieval scope through extra JSON fields on chat requests (`product` required when `project`/`build` set):

```json
{
  "model": "ee-wiki",
  "messages": [{"role": "user", "content": "RMII 接口说明"}],
  "product": "iphone",
  "project": "logan",
  "build": "p1"
}
```

If your Open WebUI build cannot send custom fields on chat requests, use `POST /v1/query` directly or the CLI:

```bash
python scripts/ask.py "RMII 接口说明" --product iphone --project logan --build p1
```

Without scope fields, EE-Wiki can **infer scope from the question** when `generation.scope_inference` is enabled (default: `true`). Examples:

- `Logan p1 lcd的pin有哪些` → product `logan`, revision `p1`, build-layer retrieval
- `logan common 架构` → project-wide `common` knowledge for `logan`
- `global CH340` → enterprise `global` layer (not a product name)

`global` and `common` are **knowledge layers**, not product or revision names. API `project` / `build` fields still override inferred scope when provided.

When scope cannot be inferred, retrieval searches the **entire index**; answers should list findings **per scope** and recommend specifying scope for build-level conclusions.

## MCP / engineering tools from Open WebUI

EE-Wiki already grounds chat answers via RAG on `/v1/chat/completions`. Separate **tool calls** (component lookup, schematic-only search, inventory) are useful when a model outside EE-Wiki’s chat path should query the index explicitly.

| Client | What works |
|--------|------------|
| **Cursor / Claude Desktop** | Direct **stdio** MCP (`scripts/mcp_serve.py`) — see [mcp.md](mcp.md) |
| **Open WebUI (typical Docker)** | **REST** against EE-Wiki API (recommended). Native MCP is **Streamable HTTP only** (Open WebUI ≥ 0.6.31); EE-Wiki ships **stdio only**, so Open WebUI cannot spawn `mcp_serve.py` inside the container |
| **Open WebUI + mcpo** | Optional bridge: run [mcpo](https://github.com/open-webui/mcpo) on the **host** next to EE-Wiki indexes, register the OpenAPI URL as an External Tool |

### Recommended path: REST (Docker / LAN)

Keep Open WebUI pointed at `http://<ee-wiki-host>:8080/v1` for chat. For explicit tool-like lookups, call the same process that MCP tools wrap:

| Need | REST | MCP equivalent |
|------|------|----------------|
| Designator / part number | `GET /v1/components/search?q=…&project=…&build=…` | `search_component_tool` |
| Scoped RAG (schematic, datasheet, general) | `POST /v1/query` with `project` / `build` / optional `document_type` | `query_schematic_tool`, `search_datasheet_tool`, `engineering_search_tool` |
| Indexed inventory | `GET /v1/projects` | `list_projects_tool` |

Pass `project` and `build` whenever possible. Scope inheritance matches MCP (`build` → `common` → `global`). Full contracts: [api-overview.md](../architecture/api-overview.md), [mcp.md](mcp.md).

Chat through EE-Wiki already answers inventory questions (“有哪些项目”) without a separate tool call.

### Optional path: mcpo → Open WebUI External Tools

Use when you want Open WebUI’s tool picker to invoke the same handlers as Cursor MCP. Requires host access to the EE-Wiki venv and `data/indexes/` (do not expect this inside a stock Open WebUI-only container).

**Prerequisites**

1. Indexes built (`python scripts/sync.py` or ingest + index)
2. Same venv as API/MCP: `pip install -e ".[tools]"` (and `ml` extras if embeddings are needed for hybrid tools)
3. [mcpo](https://github.com/open-webui/mcpo) available on the host (`uvx mcpo` or install separately)
4. Open WebUI can reach the host port (Docker: `host.docker.internal`, not `localhost`)

**Start mcpo wrapping EE-Wiki stdio MCP**

```bash
cd /absolute/path/to/EE-Wiki
source .venv/bin/activate
uvx mcpo --host 0.0.0.0 --port 8000 -- \
  /absolute/path/to/EE-Wiki/.venv/bin/python \
  /absolute/path/to/EE-Wiki/scripts/mcp_serve.py
```

Or a Claude-style config file:

```json
{
  "mcpServers": {
    "ee-wiki": {
      "command": "/absolute/path/to/EE-Wiki/.venv/bin/python",
      "args": ["/absolute/path/to/EE-Wiki/scripts/mcp_serve.py"]
    }
  }
}
```

```bash
uvx mcpo --host 0.0.0.0 --port 8000 --config /path/to/ee-wiki-mcp.json
```

**Register in Open WebUI**

1. **Admin Settings → External Tools → +**
2. Type: **OpenAPI** (mcpo exposes OpenAPI, not Streamable HTTP MCP)
3. URL: `http://host.docker.internal:8000/ee-wiki` when using a named config entry, or the single-server root mcpo prints on startup (often `http://host.docker.internal:8000`)
4. Auth: **None** unless you started mcpo with an API key
5. Enable the tool in the chat **+ → Tools** panel

Tools that should appear (names may be prefixed by mcpo): `search_component_tool`, `query_schematic_tool`, `search_datasheet_tool`, `engineering_search_tool`, `list_projects_tool`. Each retrieval tool accepts optional `project` / `build`.

Do **not** paste Cursor `mcpServers` JSON into an OpenAPI connection, and do **not** set Type to **MCP (Streamable HTTP)** for mcpo — that path expects a Streamable HTTP MCP URL, which EE-Wiki does not serve.

### Troubleshooting (tools / MCP bridge)

| Issue | Check |
|-------|-------|
| Open WebUI cannot run `mcp_serve.py` | Expected for Docker; use REST or host-side mcpo |
| Wrong Python / `ImportError: MCP support requires…` | Use EE-Wiki `.venv` with `.[tools]`; absolute path to that interpreter in mcpo config |
| Empty tool results | Indexes exist under `data/indexes/`; MCP/mcpo cwd or config must see the same tree as `serve.py` |
| Docker tool URL fails | Use `host.docker.internal` (or host LAN IP); confirm mcpo listens on `0.0.0.0` |
| Tools missing in chat | Enable under chat **+ → Tools**; admin must add External Tools first |
| Want native “MCP (Streamable HTTP)” type | Not supported by EE-Wiki today — use mcpo (OpenAPI) or REST |

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
- [mcp.md](mcp.md) — V2 component lookup, stdio MCP, Cursor config
- [api-overview.md](../architecture/api-overview.md) — endpoint contracts
