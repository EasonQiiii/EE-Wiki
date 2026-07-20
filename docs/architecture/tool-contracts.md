# Tool contracts (agent / MCP ToolBus)

Tools invoked by agents and MCP go through [`ee_wiki.tools.bus.ToolBus`](../../src/ee_wiki/tools/bus.py).

## Runtime guarantees

| Control | Behavior |
|---------|----------|
| Timeout | `agents.tool_timeout_seconds` (default 60s) |
| Concurrency | `agents.max_concurrent_tools` |
| Scope | `ScopeEnvelope` clamps `project` / `build` |
| Write ban | Names in `BANNED_TOOLS` always refused |
| Spans | JSONL at `agents.span_log` |

## Agent-facing tools (Day-1)

| Name | Primary args | Notes |
|------|--------------|-------|
| `engineering_search` | `query`, optional `document_type`, `top_k` | Hybrid retrieval |
| `query_schematic` | `query` | Schematic chunks |
| `search_datasheet` | `query` | Datasheet chunks |
| `search_component` | `query` | Component index |
| `search_debug_case` | `query` | FA cases |
| `query_power_tree` | `query`, `direction` | Heuristic power tree |
| `evaluate_engineering_rules` | optional `rule_id` | Rules engine |
| `open_graph_node` / `graph_neighbors` | `query` | Graph reads |
| `trace_net` | `net` | **Authoritative-only** pin list |
| `connector_pins` | `refdes` | **Authoritative-only** when gated |
| `module_nets` | `module` | Always advisory |

Errors return JSON `{"error": "...", "ok": false}` from MCP wrappers, or `ToolResult.ok=False` for agents.
