# Radar Integration

**Status:** Stub + live `RadarclientBackend` ([ADR 0010](../adr/0010-fa-session-external-integrations.md)). Live path uses Apple-internal `radarclient` (not vendored in this repo) with SPNego / Kerberos.

## Why

Radar is the system of record for FA progress: diagnosis steps, pictures, attachments, and cross-project history. EE-Wiki treats `radar_id` as `case_id` and syncs state for Open WebUI FA sessions.

## Client library

| Item | Notes |
|------|-------|
| Package | `radarclient` (Apple internal zip / wheel) |
| Auth | Kerberos / AppleConnect (`gssauthenticator`); needs corporate network |
| Install | Operator machine / EE-Wiki host — e.g. extract zip onto `PYTHONPATH` or private wheel index |
| Repo policy | **Do not commit** `radarclient` sources or SSL corp PEMs into EE-Wiki git |

Reference API surface (lab demo + EE-Wiki live backend):

```python
from radarclient import (
    RadarClient,
    AuthenticationStrategySPNego,
    ClientSystemIdentifier,
    DiagnosisEntry,
)

client = RadarClient(
    AuthenticationStrategySPNego(),
    ClientSystemIdentifier("EE-Wiki", "1.0"),
)
radar = client.radar_for_id(
    101493937,
    additional_fields=["description", "diagnosis", "attachments", "pictures"],
)

# component → dict or object: name / version / id
comp = radar.component

# description + diagnosis (skip <Radar History> rows in evidence extract)
for entry in radar.description.items():
    ...
for entry in radar.diagnosis.items():
    ...

# write diagnosis (requires commit; EE-Wiki also requires confirm=true)
entry = DiagnosisEntry()
entry.text = "EE-Wiki FA note: ..."
radar.diagnosis.add(entry)
radar.commit_changes()

# attachment upload (lab demo API)
att = radar.new_attachment("xray.png")
att.set_upload_file(open("xray.png", "rb"))
att.overwrite_existing_file = True
radar.attachments.add(att)
radar.commit_changes()
```

Useful fields on `Radar`: `id`, `title`, `state`, `substate`, `component`, `description`, `diagnosis`, `attachments`, `pictures`, `foundInBuild`, `configurationSummary`, `priority`, `assignee`.

### Enable live Radar on a lab host

1. Install Apple `radarclient` on `PYTHONPATH` (do not commit it into EE-Wiki).
2. Obtain a Kerberos / AppleConnect ticket on that host (`appleconnect authenticate` or equivalent). **Never** put passwords in EE-Wiki config, `.env`, or scripts checked into git.
3. Set in `config/default.yaml` (or a local override):

```yaml
fa:
  radar:
    backend: radarclient
    client_system_name: EE-Wiki   # or your lab tool name
    client_system_version: "1.0"
```

4. Restart the API. FA check-in then calls `get_problem` → maps `description` / `diagnosis` / attachments into the evidence waterfall.

## EE-Wiki mapping

| Radar | EE-Wiki |
|-------|---------|
| Problem id | `case_id` / session `radar_id` |
| `component.name` | Scan for `data_layout.project_aliases` / canonical slug (e.g. `H340` or `Logan`) |
| `component.version` | `build` (normalize case: `P1` → `p1`) |
| Diagnosis text | Session transcript + optional confirm write-back; **FA evidence source** (with title/description) before asking user to paste |
| Description | `description.items()` Summary blocks → `RadarProblem.description` |
| Attachments / pictures | Lab photos + NG logs; names listed at check-in; upload with confirm; local cache under `data/cache/fa/{id}/` |

### Evidence waterfall (check-in)

```text
Flames fail items (live / stub / prior manual paste)
    → else Radar title + description + user diagnosis (LLM extract; skip <Radar History>)
    → else ask user to paste log / fail list
```

Corpus is cached as `data/cache/fa/{radar_id}/radar_corpus.txt` for download.

### project / build

```text
User override (aliases applied)
    → match alias or slug inside component.name + normalize(version)
    → foundInBuild / configurationSummary heuristics (optional)
    → ask user
```

甲方/乙方等混用名配在 **`data_layout.project_aliases`**（不是 Radar component 长名翻译）：

```yaml
data_layout:
  project_aliases:
    H340: iphone/logan    # 甲方代号 → data/raw/iphone/logan/
```

Never hardcode product names in `src/` beyond reading this map. Chat scope inference uses the same aliases.

## Protocol

`ee_wiki.protocols.radar.RadarBackend`:

- `get_problem(radar_id) -> RadarProblem`
- `list_diagnosis(radar_id) -> list[DiagnosisItem]`
- `list_attachments(radar_id) -> list[AttachmentMeta]`
- `add_diagnosis(radar_id, text, *, confirm: bool) -> None`
- `upload_attachment(radar_id, path, *, confirm: bool) -> None`

Writes **must** refuse when `confirm` is false (draft-only path returns preview without calling `commit_changes`).

## Stub vs live

| Backend | When |
|---------|------|
| `stub` | Default; CI; no Apple network |
| `radarclient` | Host has Kerberos ticket + `radarclient` importable; implemented in `integrations/radar/client.py` |

Stub returns synthetic problems so FA session UX can be developed offline. Live mapping is covered by `integrations/radar/map_problem.py`.

## Security

- Credentials only via environment / OS Kerberos cache — never in YAML committed to git
- Log Radar ids and high-level actions; do not log full diagnosis bodies at info level in shared logs if policy requires
- Confirm gate is mandatory for any mutating tool exposed to agents / chat

## Related

- [fa-session.md](fa-session.md)
- [integrations-flames.md](integrations-flames.md)
- Protocol: `src/ee_wiki/protocols/radar.py`
- Stub: `src/ee_wiki/integrations/radar/`
