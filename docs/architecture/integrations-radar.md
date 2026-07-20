# Radar Integration

**Status:** Contract + stub ([ADR 0010](../adr/0010-fa-session-external-integrations.md)). Live backend uses Apple-internal `radarclient` (not vendored in this repo).

## Why

Radar is the system of record for FA progress: diagnosis steps, pictures, attachments, and cross-project history. EE-Wiki treats `radar_id` as `case_id` and syncs state for Open WebUI FA sessions.

## Client library

| Item | Notes |
|------|-------|
| Package | `radarclient` (Apple internal zip / wheel) |
| Auth | Kerberos / AppleConnect (`gssauthenticator`); needs corporate network |
| Install | Operator machine / EE-Wiki host — e.g. extract zip onto `PYTHONPATH` or private wheel index |
| Repo policy | **Do not commit** `radarclient` sources or SSL corp PEMs into EE-Wiki git |

Reference API surface (from `radarclient`):

```python
from radarclient import RadarClient, DiagnosisEntry

client = RadarClient()  # uses default RadarEnvironment + Kerberos
radar = client.radar_for_id(12345678, additional_fields=["diagnosis", "attachments", "pictures"])

# component → "Name | Version" (e.g. project HW line | P1)
comp = radar.component  # dict or Component-like: name, version, id

# read diagnosis (user + history)
for entry in radar.diagnosis.items():
    ...

# write diagnosis (requires commit)
entry = DiagnosisEntry()
entry.text = "EE-Wiki FA note: ..."
radar.diagnosis.add(entry)
radar.commit_changes()

# attachment upload
att = radar.new_attachment("xray.png")
att.set_upload_content(path_or_bytes)
radar.attachments.add(att)
radar.commit_changes()
```

Useful fields on `Radar`: `id`, `title`, `state`, `substate`, `component`, `diagnosis`, `attachments`, `pictures`, `foundInBuild`, `configurationSummary`, `priority`, `assignee`.

## EE-Wiki mapping

| Radar | EE-Wiki |
|-------|---------|
| Problem id | `case_id` / session `radar_id` |
| `component.name` | Scan for `data_layout.project_aliases` / canonical slug (e.g. `H340` or `Logan`) |
| `component.version` | `build` (normalize case: `P1` → `p1`) |
| Diagnosis text | Session transcript + optional confirm write-back |
| Attachments / pictures | Lab photos; upload with confirm; local cache under `data/cache/fa/{id}/` |

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
| `radarclient` | Host has Kerberos ticket + `radarclient` importable |

Stub returns synthetic problems so FA session UX can be developed offline.

## Security

- Credentials only via environment / OS Kerberos cache — never in YAML committed to git
- Log Radar ids and high-level actions; do not log full diagnosis bodies at info level in shared logs if policy requires
- Confirm gate is mandatory for any mutating tool exposed to agents / chat

## Related

- [fa-session.md](fa-session.md)
- [integrations-flames.md](integrations-flames.md)
- Protocol: `src/ee_wiki/protocols/radar.py`
- Stub: `src/ee_wiki/integrations/radar/`
