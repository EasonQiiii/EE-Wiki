# MCP & V2 Query Tools

How to use EE-Wiki **V2** retrieval tools: component lookup, scoped search, MCP for Cursor/Claude, and the HTTP ingest admin API.

## Prerequisites

```bash
cd /path/to/EE-Wiki
source .venv/bin/activate
pip install -e ".[dev,ml,tools,api]"
```

Indexes must be built first — see [index.md](index.md) and [ingest.md](ingest.md):

```bash
python scripts/sync.py --force   # after V2 metadata changes, re-ingest + re-index
```

---

## Component lookup (`GET /v1/components/search`)

Exact lookup of schematic **designators** (e.g. `U101`) or **part numbers** (e.g. `STM32F407VGT6`) against `data/indexes/components.json`.

Start the API:

```bash
python scripts/serve.py
```

Example:

```bash
curl "http://localhost:8080/v1/components/search?q=U101&project=logan&build=p1"
```

| Param | Meaning |
|-------|---------|
| `q` | Designator or part number (required) |
| `project` | Optional project filter |
| `build` | Optional build filter |
| `limit` | Max hits (default 20) |

Scope follows `retrieval.scope_inheritance` (build → `common` → `global`). Response hits include `scope` (`build`, `common`, `global`), `chunk_id`, `source_file`, `page`, and `excerpt`.

The component index is built automatically during `scripts/index.py` / `scripts/sync.py`. Re-index after schematic or datasheet ingest so new `major_components` / part-number keywords appear in `components.json`.

---

## HTTP ingest admin (`POST /v1/ingest`)

Triggers the same pipeline as `scripts/sync.py` (ingest raw → processed, then build/update indexes). Useful for LAN automation without SSH.

```bash
curl -X POST http://localhost:8080/v1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"project":"logan","build":"p1","force":true}'
```

| Field | Meaning |
|-------|---------|
| `path` | Single file or directory under `data/raw/` |
| `paths` | List of paths (mutually exclusive with `path`) |
| `project` / `build` | Scope when no path given |
| `force` | Re-ingest/rebuild even when fingerprints match |
| `ingest_only` | Skip index build |
| `index_only` | Skip ingest |

**Security:** V1/V2 do not enforce auth on this endpoint. Restrict to admin networks or add a reverse-proxy API key before exposing on LAN.

Full request/response contract: [api-overview.md](../architecture/api-overview.md).

---

## MCP server (stdio)

EE-Wiki exposes read-only engineering tools for Cursor, Claude Desktop, and other MCP clients.

Start:

```bash
python scripts/mcp_serve.py
```

| Tool | Purpose |
|------|---------|
| `search_component_tool` | Part number / designator lookup |
| `query_schematic_tool` | Hybrid retrieval, `document_type=schematic` |
| `search_datasheet_tool` | Hybrid retrieval, `document_type=datasheet` |
| `engineering_search_tool` | General hybrid retrieval |

All tools accept optional `project`, `build`, and return JSON with `scope` labels.

### Cursor configuration

```json
{
  "mcpServers": {
    "ee-wiki": {
      "command": "python",
      "args": ["/absolute/path/to/EE-Wiki/scripts/mcp_serve.py"]
    }
  }
}
```

Use the same Python environment where `pip install -e ".[tools]"` was run.

---

## When to re-sync after V2 changes

Re-ingest and re-index when you need:

| Feature | Requires |
|---------|----------|
| Schematic per-page `major_components` | Re-ingest `sch/` PDFs (writes `pages` in sidecar) + re-index |
| Datasheet VLM + structured fields | Re-ingest `datasheet/` PDFs + re-index |
| FA keywords (`failure_analysis`) | Re-ingest `fa/` documents + re-index |
| `components.json` | Re-index (built from chunk metadata) |

```bash
python scripts/sync.py --force
# or
curl -X POST http://localhost:8080/v1/ingest -H 'Content-Type: application/json' -d '{"force":true}'
```

---

## Related docs

- [query.md](query.md) — CLI retrieval and RAG
- [ingest.md](ingest.md) — V2 ingest metadata (datasheet VLM, schematic pages, FA)
- [index.md](index.md) — `components.json` and index bundle
- [api-overview.md](../architecture/api-overview.md) — full REST contracts
- [open-webui.md](open-webui.md) — chat UI integration
