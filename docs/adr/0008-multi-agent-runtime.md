# 0008. Multi-Agent Runtime (V4)

Date: 2026-07-17
Status: accepted (2026-07-18)

## Context

EE-Wiki V1–V3 deliver a single-turn RAG path: retrieve → (optional graph/rules tools) → generate, with citations and `project` / `build` / `common` / `global` scope labeling. V3 completes the knowledge graph, debug cases, power tree, and engineering rules behind HTTP and MCP ([ADR 0006](0006-knowledge-graph-store.md)).

V4 adds **multi-agent orchestration**: several specialist roles (e.g. HW / FA / PCB / Mfg / SI / Power) cooperate on one engineering question. That is a **new runtime layer**, not a set of extra prompts. Constraints from AGENTS.md still apply:

- **Humans define architecture; AI fills details** — cross-module boundaries need an ADR before code
- **Knowledge first** — LLMs reason; indexes/graph/rules are the source of truth; insufficient context must not be invented away
- **Offline first** — no required cloud orchestration SaaS
- **Modular boundaries** — parser / retriever / generator / knowledge stay separate; agents orchestrate, they do not parse or own storage
- **No hardcoded project or role logic in `src/`** — roles belong in config + prompts
- **Dependency direction** — higher layers may call lower; never reverse

Today:

- There is **no** `src/ee_wiki/agents/` package (reserved in [repository-structure.md](../architecture/repository-structure.md))
- MCP tools in `src/ee_wiki/tools/` are the reusable capability surface (search, graph, power tree, rules, inventory)
- HTTP RAG already has request timeout and concurrency gates; MCP/tool calls do not yet share a hardened runtime
- Golden RAG eval exists (`docs/eval/`, `scripts/eval_rag.py`) but is not the multi-turn agent harness

This ADR locks the **interaction paradigm**, **module boundaries**, **write bans**, and **non-goals** before any `agents/` implementation.

## Decision

### 1. Recommended paradigm: Supervisor + read-only ToolBus

**Default V4 architecture:**

```text
User / API
    │
    ▼
Supervisor agent          # route, budget, fuse, refuse
    │
    ├── Specialist agents # HW, FA, PCB, Mfg, SI, Power (config-driven)
    │
    └── ToolBus           # sole gateway to capabilities
            │
            ▼
    tools/handlers.py     # existing MCP/HTTP implementations (read-only)
            │
            ├── retrieval / graph.query / rules / indexes
            └── (never) graph.store write, ingest, index rebuild
```

| Piece | Role |
|-------|------|
| **Supervisor** | Owns the user turn: choose specialists, enforce budgets, merge answers, decide insufficient vs continue, own `project`/`build` scope envelope |
| **Specialists** | Narrow prompts + tool allowlists; produce scoped findings with citations; may mark `insufficient` for their slice |
| **ToolBus** | Single process-local gateway: timeout, concurrency limits, arg digest / short-TTL cache for idempotent reads, structured span logs; wraps `tools/handlers.py` |
| **SessionState** | Ephemeral per-turn (or short-lived session) blackboard: question, scope, intermediate findings, citations, insufficient flags — **not** a second knowledge store |

**Rejected as V4 defaults** (may be revisited in a later ADR):

| Paradigm | Why not first |
|----------|----------------|
| Peer debate / multi-critic loops | High token cost; amplifies confident wrong consensus; hard to eval |
| Persistent shared blackboard writing into graph/indexes | Violates knowledge-first and ADR 0006 write ownership |
| Pure fixed pipeline (always HW→FA→…) | Too rigid for inventory / power / FA-shaped questions; supervisor routing is cheaper |

Pipeline *stages inside one specialist* (retrieve → tool → draft) remain fine; the **cross-role** control plane is supervisor-routed, not a fixed global DAG.

### 2. Roles are configuration, not classes

Specialist identities (HW / FA / PCB / Mfg / SI / Power) **must not** be six hardcoded Python subclasses.

| Artifact | Location (planned) | Contents |
|----------|--------------------|----------|
| Role pack | `config/agents/roles/*.yaml` | `id`, display name, tool allowlist, default task hints, step/token budgets overrides |
| Runtime | `config/agents/runtime.yaml` (or `config/default.yaml` → `agents`) | supervisor settings, global `max_steps` / `max_tool_calls` / `max_tokens` / wall-clock |
| Prompts | `prompts/agents/{role}/` + shared `prompts/_shared/` | system/task templates; scope and graph rules reused |

Code under `src/ee_wiki/agents/` loads role packs and runs a generic specialist runner. Adding a seventh role is a config + prompt change, not a new module.

Ship order: prove supervisor + ToolBus with **two** roles first; expand the six-role pack after the harness works.

### 3. Module boundary and dependency direction

| Layer | May do | Must not |
|-------|--------|----------|
| `src/ee_wiki/agents/` | Orchestrate supervisors/specialists; call ToolBus; assemble final answer + citations | Import `graph.store` write APIs; call ingest/index pipelines; parse raw files; open `data/graph/` for mutation |
| `tools/` | Execute read-only handlers; shared tool runtime (timeout / limits / spans) | Embed agent routing logic |
| `generation/` | LLM calls for agent turns (via existing backends) | Own multi-agent policy or tool allowlists |
| `api/` | Thin HTTP entry for orchestrated chat (when exposed) | Bypass ToolBus scope envelope |
| `graph/` / `retrieval/` / `rules/` | Unchanged query/eval services | Know about agents |

Update dependency sketch:

```text
api
 ↓
agents, generation, tools, graph, rules
 ↓
retrieval
 ↓
knowledge
 ↓
ingestion
 ↓
common, protocols
```

`agents` sits beside `generation` / `tools` as an orchestration layer. Prefer a small `protocols/agent.py` (or tool-runner protocol) before a second orchestration backend.

### 4. Write bans and capability sandbox

Multi-agent magnifies misuse. V4 **hard-bans** the following from every agent tool allowlist:

- `POST /v1/ingest` and any ingest/index/sync/build-graph entry points
- Direct writes to `data/processed/`, `data/indexes/`, `data/graph/`
- Any future “enrich graph from conversation” API unless a **separate** ADR amends this one

Knowledge refresh remains operator/CLI (and optional authenticated ingest admin), never an agent side effect.

**External** FA side effects (Radar diagnosis/attachments, Keynote under `data/exports/`) are **not** covered by this ban; they are defined in [ADR 0010](0010-fa-session-external-integrations.md) and require explicit user confirm for Radar writes.

Graph **query** tools (`open_graph_node`, neighbors, path, filter, power tree, rules evaluate) stay available as **reads**. Concurrent agent reads do not require graph file locks; `build_graph` / ingest continue to own persistence (prefer atomic replace). Agents must not be designed to “enrich” the JSONL store at runtime.

### 5. Scope envelope (central guard)

All tool calls go through a **ScopeContext** (or equivalent) held by the supervisor and attached by ToolBus:

- Callers supply `project` / `build` (and inheritance flags from config)
- Specialists **cannot** widen scope on their own; only the supervisor may broaden or narrow
- Omitting scope is an explicit policy (document in config): either refuse tools that need scope, or search with documented inheritance — never “silently global then claim build truth”
- Agent-triggered **external write-backs** (e.g. Radar diagnosis/attachments per [ADR 0010](0010-fa-session-external-integrations.md)) must carry the same ScopeContext; confirm alone is not enough

This is an **agent sandbox** over the existing filter + inheritance model, not full multi-tenant IAM. Product ACLs can layer later without changing the ToolBus contract.

### 6. Budgets, fusion, and insufficient knowledge

| Control | Requirement |
|---------|-------------|
| Step / tool / token / wall-clock budgets | Config-driven; exceed → stop specialists, supervisor returns best-effort fused answer **or** insufficient — never unbounded loops |
| Insufficient propagation | If required evidence is missing, specialists set `insufficient`; supervisor **must not** let another role invent compensating facts. Allowed: more retrieval within scope, ask user, or explicit insufficient |
| Citations | Final user-visible answer keeps document/page/chunk (and graph node ids when used) provenance |
| Heuristic graph/power edges | Same honesty as V3 prompts: candidates, not CAD-verified netlist truth |

Empty-retrieval hard refusal from single-turn RAG remains the model for “no evidence”; multi-agent must not weaken it via cross-role padding.

### 7. Observability and eval (contract level)

Before treating V4 as shippable:

- Every ToolBus call emits a structured span: who (supervisor/specialist id), tool, arg digest, latency, ok/error code
- Agent eval harness scores **question → trajectory → final answer + citations** (schema under `docs/eval/`); distinct from single-turn `eval_rag`
- Single-turn retrieval golden QA remains the regression floor for the knowledge layer agents stand on

Implementation detail (JSONL spans vs OpenTelemetry export) is deferred to code; offline-first prefers local artifacts by default.

### 8. Prerequisites (implementation gate)

Do **not** land `src/ee_wiki/agents/` orchestration until, at minimum:

1. This ADR is **accepted**
2. Tool contracts (inputs/outputs/error codes/timeouts) are frozen for handlers agents will call
3. Shared tool runtime exists (timeout + concurrency limit + spans) usable by MCP and ToolBus
4. Retrieval golden eval is a CI gate (retrieval mode); graph/power fixture regression exists for heuristic floors
5. Dependency lockfile supports reproducible offline installs

Details of those hardening tasks are execution plan, not re-decided here.

## Out of scope / non-goals (this ADR)

Explicitly **not** decided or delivered by accepting this ADR alone:

- Implementing `src/ee_wiki/agents/` (follow-up after acceptance + prerequisites)
- Debate-style or swarm multi-agent as the default control plane
- Persistent blackboard that writes conversation conclusions into the knowledge graph or indexes
- Agent-triggered ingest, index rebuild, or graph build
- Cloud agent platforms, hosted Lang* control planes, or required telemetry backends
- Full six-role production tuning on day one (config skeleton yes; quality bar after harness)
- Multi-tenant authZ / per-user ACL beyond ToolBus scope envelope and existing optional ingest API key
- Replacing Open WebUI; EE-Wiki remains the backend knowledge/orchestration engine
- Changing ADR 0006 store format or allowing generation/agents to open graph store files for write
- Guaranteeing power-tree / connectivity heuristics as board truth (golden floors only)

## Consequences

### Positive

- Clean greenfield: paradigm and write bans fixed before code spreads
- Reuses V2/V3 MCP handlers as the capability surface — agents do not fork retrieval/graph logic
- Roles stay data-driven, aligned with “no hardcoded project code”
- Insufficient and scope rules scale to multi-agent without “helpful” hallucination loops
- Ops model stays offline: local ToolBus + existing LLM backends ([ADR 0003](0003-external-llm-openai-compatible.md) included)

### Negative / limits

- Supervisor is a single planning bottleneck (acceptable for V4; shard later if needed)
- Read-only tools mean agents cannot “fix the corpus” mid-conversation — operators still own ingest
- Config/YAML role packs need discipline (schema validation) or bad allowlists ship silently
- Token and latency cost rises vs single-turn RAG — budgets are mandatory, not optional polish

### Follow-ups (after acceptance)

1. ~~Harden `tools/` runtime + publish tool-contract doc/tests (shared by MCP and ToolBus)~~ — `tools/bus.py` + MCP via ToolBus
2. ~~Scope envelope helper used by all handlers entry points~~ — `tools/scope.py` + ToolBus clamp
3. ~~Scaffold `src/ee_wiki/agents/` + `config/agents/` + `prompts/agents/` per this ADR~~ — six roles (fa/hw/power/pcb/si/mfg); see [docs/usage/agents.md](../usage/agents.md)
4. Agent trajectory eval schema + fixture cases
5. Optional HTTP route for orchestrated chat (document in `docs/architecture/api-overview.md` when added) — chat uses `/v1/chat/completions` behind `agents.enabled`
6. Amend this ADR only if introducing agent write-back, debate default, or a second orchestration backend
7. ~~Add local-LLM semantic task/role routing~~ — validated `TASK + ROLES` when
   needed; deterministic FA/connectivity gates and specialist recipes remain
   code-enforced. A free-form LLM tool planner is still out of scope.
   **Amended by [ADR 0012](0012-chat-pipeline-grounding.md):** routing is
   rules-first; semantic LLM only on ambiguity; knowledge answers must go through
   hybrid RAG with citations (chat owns `RagService`, not Supervisor).

## References

- [AGENTS.md](../../AGENTS.md) §2–§3, §8 (V4), §16
- [ADR 0006](0006-knowledge-graph-store.md) — graph store; multi-agent was out of scope there
- [ADR 0003](0003-external-llm-openai-compatible.md) — local OpenAI-compatible LLM for concurrent generation
- [docs/usage/mcp.md](../usage/mcp.md) — current tool inventory
- [docs/architecture/repository-structure.md](../architecture/repository-structure.md) — reserved `agents/` package
