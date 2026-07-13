# 0006. Knowledge Graph Store (V3)

Date: 2026-07-13
Status: accepted (P1–P5 complete: store/build/query + Case nodes + Rail / supplies / derived_from + engineering rules + graph HTTP/MCP suite + optional retrieval enrichment; graph schema version **3**; see `src/ee_wiki/graph/` and `src/ee_wiki/rules/`)

## Context

EE-Wiki V3 introduces a **knowledge graph** over engineering entities (components, nets, interfaces, documents) so retrieval and tools can answer connectivity and scope-aware neighborhood questions that hybrid chunk search alone does not.

Constraints from AGENTS.md:

- **Offline first** — no cloud graph SaaS (Neo4j Aura, Amazon Neptune, etc.)
- **Modular boundaries** — graph owns store/build/query; retrieval may consume graph results; generation never talks to the store
- **Dependency direction** — `api` → `generation` / `tools` / `graph` → `retrieval` → `knowledge` → `ingestion` → `common` / `protocols`
- **Protocols before second backends** — define interfaces before implementing alternatives

V2 already produces graph-shaped metadata without a second PDF pipeline:

- `data/indexes/components.json` (designators / part numbers → chunk refs)
- Schematic `pages` sidecars (`major_components`, `nets`, `interfaces` on chunks)
- Datasheet structured fields (`supply_voltage`, `pin_count`, `package`, `interfaces`)

`data/graph/` and `src/ee_wiki/graph/` are reserved in the repository layout but unimplemented. This ADR locks store choice and module boundaries before P1 implementation.

## Decision

### 1. Offline, file-backed graph store (MVP)

Use a **flat on-disk graph bundle** under `data/graph/`, consistent with [ADR 0002](0002-v1-runtime-stack.md) index storage:

| File | Role |
|------|------|
| `manifest.json` | Build metadata, source fingerprints, schema version |
| `nodes.jsonl` | One JSON object per node (`id`, `type`, `project`, `build`, attributes) |
| `edges.jsonl` | One JSON object per edge (`source`, `target`, `type`, scope attrs) |

**Default MVP approach: JSONL bundle + in-process adjacency**, not SQLite and not a hosted/embedded Neo4j.

Rationale:

- Matches V1/V2 ops model (copy `data/indexes/` + `data/graph/` to backup; no daemon)
- Zero new runtime dependency for P1
- Enough for neighbor / short-path / scope-filter queries on enterprise corpora of this scale
- Backend remains swappable via `protocols/graph.py` if SQLite or NetworkX persistence is needed later

No Neo4j, Neptune, or other cloud/hosted graph databases in V3.

### 2. Module boundary

| Layer | Responsibility |
|-------|----------------|
| `src/ee_wiki/graph/` | Own store open/load/save, graph **build** from indexed artifacts, and **query** APIs |
| `retrieval/` | May call graph query interfaces to enrich or filter hybrid results |
| `generation/` | Must **not** import graph store or open `data/graph/` — only receives context already assembled upstream |
| `api/` / `tools/` | Orchestrate; thin wrappers over graph/retrieval services |

Protocol: [`src/ee_wiki/protocols/graph.py`](../../src/ee_wiki/protocols/graph.py). Package stub: `src/ee_wiki/graph/` (P0); full build/query in P1.

### 3. Build source

Derive the graph from **indexed metadata and sidecars**, not a second PDF/CAD parser pipeline:

- Chunk / document metadata already written under `data/processed/` and `data/indexes/`
- `components.json` and schematic page fields (`major_components`, `nets`, `interfaces`)
- Datasheet structured fields where they link parts to interfaces/packages

Re-running ingest/index remains the source of truth refresh; graph build is a downstream index-time or post-index step.

### 4. Scope inheritance

Graph queries **must** honor `project` / `build` / `common` / `global` the same way retrieval does (`retrieval.scope_inheritance`):

- Filter `project=X, build=Y` → include nodes/edges from `X/Y`, `X/common`, and `global`
- Prefer build-specific evidence over `common` over `global` when presenting or ranking results

Scope labels on returned nodes/edges must be explicit so callers (and eventually the LLM context layer) can distinguish layers.

### 5. Out of scope (this ADR)

- Full CAD netlist / schematic CAD import
- Multi-agent orchestration (V4)
- Cloud vector or graph databases
- Debug Case DB and Power Tree product features beyond using this store as their persistence substrate later
- Full graph build/query implementation (V3 **P1**)

## Consequences

### Positive

- Clear P0 contract: protocol + ADR before code that crosses module lines
- Ops-consistent with ADR 0002 flat on-disk artifacts
- Graph stays offline and enterprise-backup-friendly
- Retrieval can grow graph-aware features without generation coupling to storage

### Negative / limits

- In-process JSONL load may need sharding or a heavier backend for very large graphs — address behind `GraphStoreBackend` with a new ADR if required
- Path queries are best-effort BFS/Dijkstra in memory for MVP; not a substitute for a dedicated graph DB at mega-scale

### Follow-ups (P2+)

- ~~Debug Case DB / Power Tree product features on this store~~ — **P2 done:** canonical case records in `data/indexes/cases.json` (built at index time from FA metadata); Case nodes + `mentions` / `caused_by` / `related_to` edges in the graph bundle; retrieval `case_lookup` boost + `GET /v1/cases/search` / MCP `search_debug_case_tool`. Generation still never opens the store.
- ~~Power Tree product features on this store (P3)~~ — **P3 done:** `Rail` nodes; `supplies` (regulator→rail, rail→load, datasheet voltage match) and `derived_from` (rail↔net identity + rail hierarchy); heuristic extraction in `graph/power.py` (no CAD netlist); `PowerTreeQuery` + `GET /v1/power/tree` / MCP `query_power_tree_tool`; schema version bumped to **3**. Edges are co-occurrence / naming candidates — not board-verified netlist truth.
- ~~Wire deeper retrieval optional graph enrichment behind config (neighbors as context)~~ — **P5 done:** `retrieval.graph_enrichment` (default **false**) + `graph_enrichment_max_hops` / `graph_enrichment_max_nodes`; compact `[graph]` block attached to `RetrievalResult` / prompt context. Generation still never opens the store.
- Consider SQLite or NetworkX-backed store only if MVP JSONL proves insufficient (new ADR or amend this one)
- ~~Rules engine (P4)~~ — **P4 done:** config-driven YAML pack under `config/rules/`; `src/ee_wiki/rules/` evaluates graph (+ case index) → pass/fail/insufficient with citations; starter checks `rail_presence`, `power_tree_flags`, `interface_naming`, `fa_recurrence`; `GET /v1/rules` + `/v1/rules/evaluate` / MCP `list_rules_tool` / `evaluate_rules_tool` / `scripts/evaluate_rules.py`. Generation still never opens the store.
- ~~Full HTTP / MCP graph query suite (P5)~~ — **P5 done:** `GET /v1/graph/{node,neighbors,path,nodes}` + MCP `open_graph_node_tool` / `graph_neighbors_tool` / `graph_path_tool` / `graph_filter_tool`; graph-aware prompts under `prompts/_shared/graph_rules.md`, `prompts/power/`, `prompts/rules/`.