# Flames Integration

**Status:** Contract + backends ([ADR 0010](../adr/0010-fa-session-external-integrations.md)).

| Backend | Config | Role |
|---------|--------|------|
| **`manual`** (default) | `fa.flames.backend: manual` | Open WebUI paste backup — production path until Flames API exists |
| `stub` | `stub` | Synthetic logs for unit tests / offline demos |
| `live` | `live` | Real Flames API (TBD; intranet only) |

## Why

Flames stores assembly flow, station test records, and raw test logs. FA triage needs **fail items + downloadable logs**. Until the live API is available, engineers supply that evidence in chat; EE-Wiki structures it the same way a live connector would.

## Manual backup (default)

```text
User: 分析 radar 12345678
  → Radar snapshot + scope
  → Flames manual: no cache yet → ask for log / error list
User: pastes log or "- error A\n- error B"
  → ingest_fa_user_evidence → cache under data/cache/fa/{id}/
  → extract ERROR/FAIL lines (or bullets) → FailItem[]
  → download links via GET /v1/cache/fa/{id}/...
  → continue true-fail / module dialogue
```

Rules:

- Never invent fail items when evidence is missing (`needs_user_input=true`)
- Prefer full log paste; bullet / numbered lists also accepted
- Optional: station name, serial (SN)
- Same `FailItem` / cache / download contract as `live` will use later

Orchestration:

- `ee_wiki.integrations.session.start_fa_checkin` — first turn (may await paste)
- `ee_wiki.integrations.session.ingest_fa_user_evidence` — apply user paste

## Live API (future)

When intranet access exists, implement `LiveFlamesBackend` and switch:

```yaml
fa:
  flames:
    backend: live
    base_url: https://flames.example.internal
```

Document then:

1. Auth (SSO / API key / mTLS — TBD)
2. Unit lookup from Radar (serial / MLBSN — TBD)
3. List stations / attempts + raw log download
4. Canonical error markers per log format

Until then keep `manual` as the default.

## Protocol

`ee_wiki.protocols.flames.FlamesBackend`:

- `resolve_unit` / `list_test_records` / `fetch_log` / `extract_errors`
- `collect_fail_items` → `FailItemsResult` (`source`, `needs_user_input`, `user_prompt`)

`ManualFlamesBackend` adds:

- `ingest_user_evidence(radar_id, text, *, cache_dir, station=None, serial=None)`

## Config

```yaml
fa:
  flames:
    backend: manual          # manual | stub | live
    # base_url: null
    timeout_seconds: 60
```

Env (when live exists): placeholders in `.env.example` (`EE_WIKI_FLAMES_TOKEN`, …).

## Station knowledge (docs, not API)

```text
data/raw/{project}/common/sop/stations/
```

Separate from the Flames connector. See [fa-session.md](fa-session.md).

## Related

- [fa-session.md](fa-session.md)
- [integrations-radar.md](integrations-radar.md)
- `src/ee_wiki/integrations/flames/manual.py`
- `src/ee_wiki/integrations/flames/stub.py`
