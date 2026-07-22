# 0010. FA Session + Radar / Flames / Keynote Integrations

Date: 2026-07-18
Status: proposed

## Context

FA engineers track each failing unit with an Apple **Radar** id, pull assembly/test evidence from **Flames**, triage fail items, run lab analysis, update Radar diagnosis/attachments, and produce a one-page Keynote FA summary.

EE-Wiki already stores offline FA write-ups under `fa/` → `failure_analysis` and indexes them as debug cases (`cases.json`, ADR 0006 P2). It does **not** yet:

- Open a multi-turn FA session keyed by Radar id from Open WebUI
- Call Radar or Flames APIs in real time
- Export a company Keynote summary for browser download

[ADR 0008](0008-multi-agent-runtime.md) bans agents from writing the **knowledge** store (`data/processed/`, indexes, graph). Controlled write-back to **external** systems (Radar diagnosis/attachments) and local **exports** (Keynote under `data/exports/`) are a different class of side effect and need an explicit contract.

Constraints from AGENTS.md still apply: offline-first defaults, no hardcoded project names, modular boundaries, knowledge-first answers with citations.

## Decision

### 1. FA session is Radar-keyed

| Item | Rule |
|------|------|
| Session primary key | `case_id = radar_id` (one failing unit ↔ one Radar) |
| UI | Open WebUI chat against EE-Wiki `/v1/chat/completions` (orchestration later under `agents/`) |
| Entry intents | e.g. `new checkin rdar://…`, `分析 radar …` — parse Radar id, start/resume FA session |
| Scope | Prefer Radar `component` (`name` / `version`) → EE-Wiki `project` / `build`; user may override |

Session state is ephemeral (in-memory / short-lived store), **not** a second knowledge graph. Durable FA knowledge still lands via operator ingest of `fa/` docs when desired.

> **Amendment (2026-07-21, fa-session.md):** A session may start **unbound** (`radar_id = null`) when the user opens an FA investigation by symptom / part / net without a ticket. The user can **bind** a Radar id later in the same conversation (`radar://…` in a follow-up message); at that point `case_id` becomes `radar_id` and the external primary key is Radar as before. See [fa-session.md](../architecture/fa-session.md) entry C and `agents/fa_session.py:ensure_fa_session`.

### 2. Integration layer (not ingestion)

```text
Open WebUI
    │
    ▼
api/ (+ future agents/ FA supervisor)
    │
    ├── integrations/radar/     # Protocol + stub | radarclient backend
    ├── integrations/flames/    # Protocol + stub | real API when intranet available
    ├── integrations/report/    # Keynote one-pager from company template
    └── retrieval / cases / graph / rules / connectivity   # read-only knowledge tools
```

- Protocols live in `protocols/` (`RadarBackend`, `FlamesBackend`, `FaReportBackend`).

**Connectivity trace is authoritative-only.** Schematic pin/net traces must
never be answered from probabilistic VLM/OCR text. Any FA path that reaches a
trace — the chat trace intercept today, or a future `agents/` FA supervisor via
the read-only ToolBus (ADR 0008) — goes through
`ConnectivityQuery.resolve_trace`, which returns a trace only when grounded on
`cad_netlist` evidence (BoardView `.brd` is advisory-only and no longer grounds a trace — see ADR 0013 §4) and otherwise refuses (ADR 0009 §5). A
half-correct trace is worse than an explicit "insufficient" because FA
conclusions are built on it.
- Concrete backends live in `src/ee_wiki/integrations/` (stub by default).
- Do **not** vendor Apple-internal `radarclient` into git; document install path and auth (Kerberos / AppleConnect).
- Flames API details are TBD; ship stub + [integrations-flames.md](../architecture/integrations-flames.md) for a later implementer on intranet.

### 3. Phase-1 capability set (design complete; live APIs when reachable)

Even without intranet access now, the **contract** includes both read and write paths:

| Capability | Behavior |
|------------|----------|
| Radar read | Problem title/state, component, diagnosis history, attachment/picture metadata |
| Radar write | Append diagnosis text; upload attachment/picture — **only with explicit user confirm** |
| Flames read | Prefer live API when available; **default backup** is Open WebUI paste (`fa.flames.backend: manual`) → same fail-item + cache contract |
| Fail triage | Present fail list + downloadable raw-log citations; true-fail remains **human judgment**; never invent fails while awaiting paste |
| Keynote | Fill company template → `data/exports/fa/{radar_id}/FA_summary.key` |
| Download | `GET /v1/exports/fa/{radar_id}/…` (and generic `GET /v1/exports/{path}`) for Open WebUI |

Backends are config-selected:

- Radar: `fa.radar.backend: stub|radarclient`
- Flames: `fa.flames.backend: manual|stub|live` — **`manual` is the default** until the Flames API is obtainable; `stub` is for tests only

### 4. Scope extraction from Radar

Priority order:

1. Explicit user/session override (`project` / `build` in chat or API)
2. Radar `component` text + `data_layout.project_aliases` (甲方/乙方等混用名 → path slug，如 `H340` → `logan`); `version` → build (`P1` → `p1`)
3. Optional hints: `foundInBuild` / `configurationSummary` when present
4. If still unknown → ask user; do not invent scope

Cross-project FA analogy search must label results as **reference only** (similar silicon/topology), never as transferred root cause.

### 5. Write sandbox (amends ADR 0008 external side effects)

ADR 0008 knowledge write bans remain. This ADR adds:

| Allowed (with confirm) | Still banned |
|------------------------|--------------|
| Radar `diagnosis.add` + `commit_changes` | Agent-triggered ingest / index / `build_graph` |
| Radar attachment/picture upload | Writes to `data/processed/`, `data/indexes/`, `data/graph/` |
| Writes under `data/exports/fa/` and `data/cache/fa/` | Silent Radar updates without user confirm |

Tools that mutate Radar **must** require `confirm=true` (or equivalent explicit user phrase). Drafts may be shown first.

When FA is agent-driven ([ADR 0008](0008-multi-agent-runtime.md)), Radar writes must also carry the supervisor **ScopeContext** (`project` / `build`); specialists must not widen scope then write back.

### 6. Artifacts on disk

| Path | Purpose | Git |
|------|---------|-----|
| `assets/templates/fa/` | Company Keynote one-page template | versioned (no customer data) |
| `data/exports/fa/{radar_id}/` | Generated `FA_summary.key` (+ optional PDF) | gitignored via `data/` |
| `data/cache/fa/{radar_id}/` | Cached Flames logs / Radar downloads for citation links | gitignored |

Browser download uses `api.public_base_url` + `/v1/exports/...` (same pattern as `/v1/sources` and `/v1/assets`).

### 7. Documentation set

| Doc | Role |
|-----|------|
| [fa-session.md](../architecture/fa-session.md) | Open WebUI interaction + session state |
| [integrations-radar.md](../architecture/integrations-radar.md) | `radarclient` mapping, auth, confirm writes |
| [integrations-flames.md](../architecture/integrations-flames.md) | Stub contract; fill when Flames API is available |

## Consequences

### Positive

- Clear FA product shape: Radar id → triage → dialogue → Radar/Keynote closeout
- External connectors stay swappable behind protocols; stub enables offline progress
- Knowledge-store write bans preserved; Radar/export writes are explicit and confirm-gated
- Export download path matches existing citation URL model for Open WebUI

### Negative / limits

- Real Radar/Flames need Apple network + Kerberos; CI stays on stubs
- Keynote template fill may require macOS Keynote/AppleScript (parallel to ADR 0004)
- Component→project mapping may need per-program config until naming is standardized
- Full FA supervisor in `agents/` — ADR 0008 accepted; still waits on ToolBus + §8 prerequisites before implementation

### Follow-ups

1. Implement `radarclient` backend when VPN/Kerberos available
2. Fill Flames API fields in integrations-flames.md and ship real backend
3. Drop company `.key` template into `assets/templates/fa/`
4. ~~Wire FA entry intents into chat~~ — lightweight `integrations/fa_chat.py` on `/v1/chat/completions` (check-in + manual evidence). Full `agents/` FA supervisor: ADR 0008 is **accepted**; still gated on ADR 0008 §8 prerequisites (ToolBus/tool contracts/eval) before landing orchestration
5. Optional: mirror closed FA summaries into `data/raw/{project}/{build}/fa/` via operator ingest (not agent)

## References

- [ADR 0008](0008-multi-agent-runtime.md) — multi-agent runtime; knowledge write bans
- [ADR 0004](0004-iwork-macos-export.md) — Keynote on macOS
- [ADR 0006](0006-knowledge-graph-store.md) — offline cases / graph
- Apple `radarclient` (internal; not vendored here)
