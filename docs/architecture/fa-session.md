# FA Session (Radar-keyed)

**Status:** Proposed contract ([ADR 0010](../adr/0010-fa-session-external-integrations.md)). Protocols and stub backends land first; live Radar/Flames when network access exists.

## Goal

Replace the “look up Flames + Radar + similar FA + draft summary” portion of an FA engineer’s workflow inside **Open WebUI**, using **Radar id** as the only session identifier (`case_id = radar_id`).

Lab actions (bench, X-ray, T/A, probing) stay human-owned. EE-Wiki guides, retrieves, drafts, and (with confirm) writes Radar / exports Keynote.

## User journey

```text
1. Engineer opens a new Open WebUI chat (model → EE-Wiki /v1)
2. User: "new checkin rdar://12345678"  or  "帮忙分析 radar 12345678"
3. EE-Wiki:
   a. Parse radar_id
   b. Radar agent → problem + component → project/build
   c. Flames evidence (default = manual backup):
      - live: pull logs → error items
      - manual: ask user to paste log / error list (until API exists)
      - stub: synthetic logs (tests only)
   d. Cache evidence under data/cache/fa/{radar_id}/
   e. Reply with fail list + downloadable log links + Radar status
      (or a short prompt if still awaiting paste)
4. Interactive turns: true-fail judgment (human), module hints, similar cases,
   next lab steps, draft diagnosis text
   - Schematic pin/net traces are answered only from board-verified sidecars
     (`cad_netlist` / `boardview`) via `ConnectivityQuery.resolve_trace`; when no
     authoritative evidence exists the session refuses instead of guessing from
     VLM/OCR text (ADR 0009 §5, ADR 0010). "Module hints" are advisory locators,
     not verified connectivity.
5. On request + confirm: append diagnosis / upload images to Radar
6. On request: generate Keynote → data/exports/fa/{radar_id}/FA_summary.key
   and return download URL under /v1/exports/...
```

## Session state (ephemeral)

Minimum fields (implementation may use JSON on disk under `data/cache/fa/{id}/session.json` or in-memory):

| Field | Meaning |
|-------|---------|
| `radar_id` | Primary key / `case_id` |
| `project` / `build` | EE-Wiki scope (from Radar component or override) |
| `fail_items[]` | Extracted error strings + station + log path |
| `log_refs[]` | Relative paths under `data/cache/fa/` for `/v1/exports` or cache download |
| `true_fail` | User-confirmed subset / notes (optional) |
| `radar_snapshot` | Title, state, last diagnosis preview |
| `pending_writes` | Draft diagnosis / files awaiting `confirm` |

Not a knowledge-graph write. Closed cases become durable knowledge only if an operator ingests an FA doc under `fa/`.

## Scope resolution

See [integrations-radar.md](integrations-radar.md#project--build). Order: user override → component map → `foundInBuild` / summary hints → ask user.

## Open WebUI surface

| Need | Mechanism |
|------|-----------|
| Chat entry | `POST /v1/chat/completions` → `integrations/fa_chat.py` before RAG |
| Check-in intents | `分析 radar …` / `new checkin rdar://…` / bare `rdar://…` |
| Evidence paste | After assistant “Need test evidence”, paste log or `- fail` list (optional `station: FQT`) |
| Download logs / Keynote | `GET /v1/exports/fa/{radar_id}/…` and `/v1/cache/…` with `api.public_base_url` |
| Citations to wiki docs | Existing `/v1/sources` + `sources[]` chips (normal RAG turns) |
| Full agent supervisor | Still gated on ADR 0008 §8 — this path is intentional lightweight routing |

Engineers should be able to click a link in the assistant message and download `FA_summary.key` or a cached `.log` without leaving the browser.

## Related docs

- [integrations-radar.md](integrations-radar.md)
- [integrations-flames.md](integrations-flames.md)
- [open-webui.md](../usage/open-webui.md)
- [ADR 0010](../adr/0010-fa-session-external-integrations.md)
