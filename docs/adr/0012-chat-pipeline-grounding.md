# 0012. Chat Pipeline Grounding (Gates, Route, Hybrid RAG)

Date: 2026-07-20
Status: accepted (2026-07-20)

## Context

V4 chat ([ADR 0008](0008-multi-agent-runtime.md)) routes through a Supervisor when
`agents.enabled` is true. Production behavior has drifted into three compliance
and latency problems:

1. **Citation gap (AGENTS.md §2)** — When specialists return useful findings,
   `chat.py` calls `stream_direct` on fused evidence with `citations=[]`. When
   fusion is insufficient, the chat layer emits a hard "知识不足" markdown and
   **never** falls back to hybrid retrieval. Both paths produce user-visible
   answers without retrieved document/page/chunk provenance.
2. **Duplicate hard gates** — FA check-in (`try_fa_chat_reply`) and authoritative
   connectivity (`answer_trace_question`) run inside `Supervisor.handle` and again
   in the `agents.enabled: false` cascade in `chat.py`, inviting behavior drift.
3. **TASK / LLM stack** — Supervisor semantic routing (`classify_agent_route`) runs
   for every non-gate turn, including pure wiki questions that end as
   `ROLES: none`. Passthrough still pays prepare (rewrite/scope). Legacy
   `classify_task` remains available when `caller_task` is unset; ownership of
   TASK for an agent-owned turn must be explicit. Keyword role selection already
   exists but only as a **fallback after** the routing LLM.

Scope is also resolved in multiple places (API body, prepare, retrieval merge,
FA session, `ScopeEnvelope`). In-turn re-discovery and cross-turn memory must
not be conflated.

This ADR amends the **chat orchestration contract** for ADR 0008 without
changing ToolBus write bans or role-pack configuration.

## Decision

### 1. Target pipeline (amended: Supervisor-first + FaMode)

**WikiMode** (default engineering Q&A):

```text
question
  → TurnScope lock once (API body → NL infer if incomplete → lock)
  → connectivity answer_trace_question (trace intents only; refuse or pin table)
  → FaMode gate (radar / FA session / FA intent) — else stay wiki
  → Supervisor (when agents.enabled)
       ├─ clarify — underspecified / needs scope (no RAG)
       ├─ respond — FA transitional (no RAG)
       ├─ passthrough — no specialist → hybrid RAG
       └─ hybrid — specialists + ToolBus → fuse → hybrid RAG + citations
  → RequestTrace spans for the turn
```

**FaMode** (FA assistant — target; see [fa-session.md](../architecture/fa-session.md)):

```text
question
  → FaMode if: radar:// | FA session in history | FA intent (LLM MODE classify)
  → FaAgent on shared ToolBus (radar_id may be null → unbound session)
       Act → Exec → EvidenceBundle → Say
  → respond (no silent RAG); later message may bind radar://
```

FA / Flames / authoritative connectivity are **ToolBus skills** (allowlist per agent).
Authority and reject rules are enforced in tools (ADR 0009/0010). **In addition**,
chat re-applies the deterministic :func:`answer_trace_question` gate for detected
trace intents so hybrid RAG / Supervisor prose can never invent pin paths when
intent detection fails to reach tools, or rewrite a pin list into a fake
「起点→终点」narrative.

| Branch | User-visible citations | Notes |
|--------|------------------------|-------|
| `clarify` / `respond` | Optional; no KB chunk requirement | Supervisor-produced; not hybrid RAG |
| Open WebUI auxiliary bypass | None | Unchanged; no knowledge claim |
| `passthrough` / `hybrid` | Required from retrieval chunks when chunks exist | Knowledge-answer path |
| True insufficient | N/A | Only after hybrid retrieve yields nothing |

### 2. Orchestration ownership (no `agents → generation` hard dependency)

- **`api/` (chat)** owns: calling Supervisor, and **all** calls into
  `RagService.answer` / `stream_answer` for knowledge answers.
- **`agents/`** returns intent only: `SupervisorResult.kind` ∈
  `{clarify, respond, passthrough, hybrid}`.
- Supervisor **must not** import or call `RagService`. Chat maps:
  - `clarify` / `respond` → stream markdown only (no RAG)
  - `hybrid` → `stream_answer(..., task=..., agent_evidence=..., task_owner=supervisor)`
  - `passthrough` → same without evidence (or empty evidence)
  - fused insufficient → still `hybrid` with empty evidence (RAG fallback), **not**
    a terminal `insufficient` short-circuit at the chat layer

Deprecated chat behavior: `kind == "rag"` + `stream_direct(_agent_grounded_prompt)`.

### 3. TASK ownership (runtime guard, keep `classify_task`)

Do **not** delete `classify_task` / `generation.task_classification`.

| Condition | Effective task classification |
|-----------|-------------------------------|
| This turn entered Supervisor (`agents.enabled` and past gates) | Treat `task_classification` as **false**; TASK comes only from `SupervisorResult.task` / explicit API `task` |
| `agents.enabled: false` or supervisor unavailable (`llm is None` and rules yield no task) | Existing legacy chain: API task → prepare → `classify_task` |

Document a per-turn `task_owner ∈ {supervisor, legacy}` in RequestTrace.

### 4. Rules-first routing; semantic route only on ambiguity

Order inside Supervisor (after gates removed):

1. Explicit API `requested_task` → map roles (unchanged).
2. **`cheap_route`**: role-pack keywords / deterministic heuristics → if score clear
   and roles non-empty, or clear "no specialist" → return without LLM.
3. **`classify_agent_route`** only when cheap route is empty/ambiguous **and** an
   LLM is available.
4. Keyword fallback remains the last resort when semantic parse fails.

Thresholds prefer **false negative on specialists** (extra passthrough RAG) over
false positive tool fan-out.

### 5. Connectivity answer-grade gate (amended)

Trace intents (``完整trace`` / ``追网`` / …) are answered by the deterministic
:func:`answer_trace_question` gate in chat **before** FaMode / Supervisor /
hybrid RAG. ToolBus ``trace_net`` / ``connector_pins`` remain authoritative for
agent turns; the chat gate exists so hybrid prose can never invent pin paths
when intent would otherwise miss tools.

FA check-in remains FaMode / ``radar`` tools (not a duplicate chat hard gate).

### 6. TurnScope vs DialogScope

| Concept | Lifetime | Rule |
|---------|----------|------|
| **TurnScope** | One HTTP `/chat/completions` request | Locked once in chat (`API body` → `merge_scope_from_question` when incomplete) **before** connectivity / FaAgent / Supervisor / tools / RAG. Downstream **reads** it; FaSession and ToolBus must **not** re-infer conflicting product/project/build for the same turn. |
| **DialogScope** | Multi-turn session (future / FA) | Default inherit from prior FA header axes when caller left them unset; change only on explicit override (API fields, caller-locked utterance). **No second NL infer inside** `ensure_fa_session`. |

API-supplied scope (after `project_aliases`) wins for TurnScope. Natural-language
inference runs **at most once** at the chat lock point when API scope is empty,
then locks.

### 7. Hybrid generation contract

For `passthrough` and `hybrid`:

1. Retrieve with TurnScope (inheritance unchanged).
2. Build **one** prompt: task template + optional agent evidence block + retrieved
   context (+ scope/graph rules).
3. Stream/collect once; attach retrieval citations (stream and non-stream share
   `_prepare_and_retrieve`).
4. If retrieve returns no chunks and evidence is empty → insufficient.
5. If retrieve returns no chunks but agent evidence is non-empty → generate from
   evidence with empty chunk citations **and** log `evidence_only=true` (interim);
   follow-up work should promote tool hit provenance into `Citation` objects.

`stream_direct` remains only for Open WebUI auxiliary tasks and Supervisor
``clarify`` / ``respond`` replies (no hybrid RAG).

### 8. RequestTrace / PipelineSpan

Every knowledge turn records a structured span (local log / existing agents span
log), at minimum:

- `gate` (deprecated; always `none` under Supervisor-first)
- `route_mode` (rules | semantic | explicit | none)
- `task_owner`, `task`, `roles`
- `llm_calls` count or list
- `scope_source` (api | infer | fa | none)
- `branch` (clarify | respond | hybrid | passthrough | insufficient)
- `phase_ms` for gate / route / tools / retrieve / generate

No required cloud telemetry (offline-first).

### 9. Dual exit constraint

`answer` and `stream_answer` must share the hybrid evidence path. Chat must not
implement fallback on only one of stream vs non-stream.

## Out of scope / non-goals

- Merging route + prepare into a single early LLM call (P2; revisit after
  RequestTrace shows prepare remains hot once rules-first routing lands)
- Full DialogScope / session memory redesign beyond FA
- Populating rich `Citation` objects from every ToolBus JSON hit (follow-up)
- Changing ADR 0008 write bans, role YAML layout, or ToolBus sandbox
- Debate-style multi-agent

## Consequences

### Positive

- Restores AGENTS.md §2 grounding for agent-involved knowledge answers
- One gate implementation; supervisor focuses on route → tools → fuse intent
- Fewer routing LLM calls on ordinary wiki questions
- Measurable pipeline via RequestTrace

### Negative / limits

- Hybrid after specialists adds retrieve latency vs today's evidence-only
  `stream_direct` (accepted cost of citations)
- Evidence-only generation when retrieve is empty is an interim citation hole
- Chat orchestration grows slightly more explicit branching

### Follow-ups

1. Implement gates module + slim Supervisor + hybrid chat wiring (this ADR)
2. RequestTrace fields on the hot path + lab smoke checklist in `docs/usage/agents.md`
3. Tool → `Citation` promotion; tighten evidence-only policy
4. Optional route∪prepare merge if spans justify it
5. Amend [ADR 0008](0008-multi-agent-runtime.md) follow-up #7: semantic route is
   **conditional**, not once-per-turn unconditional

## References

- [AGENTS.md](../../AGENTS.md) §2 (knowledge first / citations), §8 (V4)
- [ADR 0008](0008-multi-agent-runtime.md) — Supervisor + ToolBus
- [ADR 0009](0009-multi-source-schematic-map.md) — connectivity authority
- [ADR 0010](0010-fa-session-external-integrations.md) — FA session gates
- [docs/usage/agents.md](../usage/agents.md)
