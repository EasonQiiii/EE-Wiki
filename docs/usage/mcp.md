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
curl "http://localhost:8080/v1/components/search?q=U101&product=iphone&project=logan&build=p1"
```

| Param | Meaning |
|-------|---------|
| `q` | Designator or part number (required) |
| `product` | Optional product filter (required when project/build set) |
| `project` | Optional project filter |
| `build` | Optional build filter |
| `limit` | Max hits (default 20) |

Scope follows `retrieval.scope_inheritance` (build → project `common` → product `common` → `global`). Response hits include `scope` (`build`, `common`, `global`), `chunk_id`, `source_file`, `page`, and `excerpt`.

The component index is built automatically during `scripts/index.py` / `scripts/sync.py`. Re-index after schematic or datasheet ingest so new `major_components` / part-number keywords appear in `components.json`.

---

## HTTP ingest admin (`POST /v1/ingest`)

Triggers the same pipeline as `scripts/sync.py` (ingest raw → processed, then build/update indexes). Useful for LAN automation without SSH.

**Sync** (default — waits for completion):

```bash
curl -X POST http://localhost:8080/v1/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: '"$EE_WIKI_INGEST_API_KEY" \
  -d '{"product":"iphone","project":"logan","build":"p1","force":true}'
```

**Async** (202 + poll — preferred for large VLM batches):

```bash
# Start job
curl -X POST http://localhost:8080/v1/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: '"$EE_WIKI_INGEST_API_KEY" \
  -d '{"product":"iphone","project":"logan","build":"p1","force":true,"async":true}'
# → {"job_id":"...","status":"queued","status_url":"/v1/ingest/jobs/..."}

# Poll until succeeded|failed
curl -H 'X-API-Key: '"$EE_WIKI_INGEST_API_KEY" \
  http://localhost:8080/v1/ingest/jobs/<job_id>
```

| Field | Meaning |
|-------|---------|
| `path` | Single file or directory under `data/raw/` |
| `paths` | List of paths (mutually exclusive with `path`) |
| `product` / `project` / `build` | Scope when no path given |
| `force` | Re-ingest/rebuild even when fingerprints match |
| `ingest_only` | Skip index build |
| `index_only` | Skip ingest |
| `async` | `true` → 202 + background job; poll `GET /v1/ingest/jobs/{job_id}` |

Config: `api.max_concurrent_ingest_jobs` (default `1`). Jobs are in-memory and lost on server restart.

**Security (optional API key):** set `EE_WIKI_INGEST_API_KEY` to require `X-API-Key` or `Authorization: Bearer` on ingest routes. When unset, ingest stays open (local-dev friendly); binding `0.0.0.0` without a key logs a startup warning. Chat/query remain unauthenticated.

Full request/response contract: [api-overview.md](../architecture/api-overview.md).

---

## MCP server (stdio)

EE-Wiki exposes read-only engineering tools over **stdio** for Cursor, Claude Desktop, and other local MCP clients.

Start (from the EE-Wiki venv):

```bash
pip install -e ".[tools]"   # if not already installed
python scripts/mcp_serve.py
```

| Tool | Purpose |
|------|---------|
| `search_component_tool` | Part number / designator lookup |
| `search_debug_case_tool` | Debug / FA case lookup (symptom, part, net, case id) |
| `query_power_tree_tool` | Heuristic power tree (`feeds` / `powers` / `tree` / `flags`) |
| `list_rules_tool` | List engineering rules from `config/rules/` |
| `evaluate_rules_tool` | Evaluate rules (pass/fail/insufficient + citations) |
| `open_graph_node_tool` | Resolve/open one graph node |
| `graph_neighbors_tool` | Graph neighbors within N hops |
| `graph_path_tool` | Shortest path between two nodes |
| `graph_filter_tool` | Filter nodes by product/project/build scope |
| `query_schematic_tool` | Hybrid retrieval, `document_type=schematic` |
| `search_datasheet_tool` | Hybrid retrieval, `document_type=datasheet` |
| `engineering_search_tool` | General hybrid retrieval |
| `list_projects_tool` | Indexed product/project/build inventory and chunk counts |
| `trace_net_tool` | Trace pins on a net (`*.connectivity.json` sidecars) |
| `connector_pins_tool` | Pin↔net list for a designator / connector |
| `module_nets_tool` | Nets for a schematic page module zone |

All retrieval tools accept optional `product`, `project`, `build`, and return JSON with `scope` labels (`build`, `project_common`, `product_common`, `global`). Scope follows `retrieval.scope_inheritance`. Power-tree, rules, and graph queries require `python scripts/build_graph.py` and honor `graph.scope_inheritance` / `graph.power_tree` / `rules.enabled`. Connectivity tools (`trace_net_tool`, …) require re-ingested `sch/` sidecars (`*.connectivity.json`, ADR 0009); missing sidecars return a JSON `error` (HTTP 503 on REST). `trace_net_tool` / `connector_pins_tool` are **authoritative-only** (ADR 0009 §5): a trace is returned only when grounded on `cad_netlist` evidence (BoardView `.brd` is advisory-only and no longer grounds a trace — see ADR 0013 §4); advisory geometry/OCR-only results are refused (`authority: "insufficient"`) instead of guessed, so agents (including any FA flow) never build conclusions on unverified connectivity. Optional RAG graph enrichment is separate (`retrieval.graph_enrichment`, default off).

The MCP process loads indexes from the same config paths as `serve.py` (`data/indexes/` by default). Run it from the EE-Wiki checkout (or with the same `EE_WIKI_*` / config overrides) so it sees the indexes you built.

### HTTP project inventory

```bash
curl "http://localhost:8080/v1/projects"
```

Chat questions like “当前知识库有多少 project / 有哪些项目” are answered from the same inventory (no document RAG).

### Cursor / Claude Desktop configuration

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

Prefer the venv’s `python` binary (where `pip install -e ".[tools]"` was run), not system Python.

### Open WebUI

Open WebUI does **not** run stdio MCP servers (native MCP is Streamable HTTP only, ≥ 0.6.31). EE-Wiki does not ship a Streamable HTTP MCP endpoint.

| Deploy | Practical choice |
|--------|------------------|
| Typical Open WebUI Docker + EE-Wiki API | **REST** — chat via `/v1`; tools via `/v1/components/search`, `/v1/query`, `/v1/projects` |
| Need tool picker + same MCP handlers | Host-side **[mcpo](https://github.com/open-webui/mcpo)** wrapping `mcp_serve.py`, register as OpenAPI External Tool |
| Cursor on the same machine | Direct stdio MCP (above) |

REST ↔ tool mapping and mcpo steps: [open-webui.md](open-webui.md#mcp--engineering-tools-from-open-webui).

### Troubleshooting (MCP)

| Issue | Check |
|-------|-------|
| `ImportError` / missing `mcp` | `pip install -e ".[tools]"` in the interpreter used by the client |
| Empty results | Indexes built; MCP process sees the same `data/indexes` as `serve.py` |
| Wrong product/project/build | Pass `product` / `project` / `build` on the tool call; inheritance still searches common tiers + `global` |
| Open WebUI Docker + stdio config | Will not work — use REST or mcpo on the host |

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
curl -X POST http://localhost:8080/v1/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: '"$EE_WIKI_INGEST_API_KEY" \
  -d '{"force":true}'
```

---

## Related docs

- [query.md](query.md) — CLI retrieval and RAG
- [ingest.md](ingest.md) — V2 ingest metadata (datasheet VLM, schematic pages, FA)
- [index.md](index.md) — `components.json` and index bundle
- [api-overview.md](../architecture/api-overview.md) — full REST contracts
- [open-webui.md](open-webui.md) — chat UI + Open WebUI MCP/tools wiring
