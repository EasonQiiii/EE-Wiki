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

### Check-in attachment policy (T0–T2)

FA check-in follows a **metadata-first** contract so Open WebUI does not sit on「检索中」while every Radar byte downloads:

| Phase | Action | Downloads bytes? |
|-------|--------|------------------|
| **T0** check-in | `get_problem` → title, state, diagnosis, fail items, attachment **inventory** (name, type, kind, cached/pending) | **No** |
| **T1** background | Only when diagnosis explicitly needs a named log/picture for grounded analysis | On demand |
| **T2** user turn | User asks「下载 / 分析 log / 有哪些附件」→ `materialize_attachment` / `download_picture` | On demand |

Streaming status (Open WebUI SSE): `正在拉取 Radar 票…` at FA check-in start;
`正在分析 FA 背景…` while the LLM reads title/description/diagnosis;
`正在下载附件 (n/m)…` during on-demand / related-evidence pulls;
`正在分析附件内容…` when the user asks to analyze a named log body.

PNG / image files use the Radar **`pictures`** collection (`download_picture`), not `attachments`.

### Evidence waterfall (check-in)

Field practice: the key context lives on the **Radar face** (title/description/diagnosis), the FA comment points at the failing log by name, and Flames is *not* the critical source (a lab Flames may be empty). So the priority is **Radar face first, Flames last**:

```text
1. Radar title            (most prominent symptom)
2. Radar description      (station / DUT / configuration)
3. Radar diagnosis        (FA notes; skip <Radar History>)
4. LLM-selected strong-related attachments
       (downloaded on demand, bounded by config.fa.checkin; body scanned for FAIL lines)
5. Flames fail items      (live / stub / prior manual paste) — lowest fallback, only if 1–4 empty
6. else ask user to paste log / fail list
```

- **Which** attachments are strong-related is decided semantically by the LLM (`prompts/fa/checkin_background.md` → `BACKGROUND` / `TRUE_FAIL_HINT` / `FA_NOTES` / `RELATED_FILES` / `UNRESOLVED`), never by an NG/FAIL filename regex (ADR 0013). Names the FA notes cite but that are not attached surface under `UNRESOLVED` and are never downloaded.
- At check-in only the LLM-selected subset is materialized (`materialize_attachment`), capped by `config.fa.checkin.max_related_files` / `max_related_file_bytes` / `max_related_total_bytes`; over-cap files are listed by name with a「下载 <名>」hint. Pictures are linked but not scanned as fail logs.
- Each fail item carries a `source` tag: `radar_title` | `radar_text` | `radar_attachment` | `flames` | `user_paste`.
- No LLM → degrade to caching the corpus + listing the full inventory (no batch download) and asking the user to paste.

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
- `download_attachment(radar_id, file_name, *, dest_path) -> Path`
- `download_picture(radar_id, file_name, *, dest_path) -> Path` (``kind == "picture"``)
- `add_diagnosis(radar_id, text, *, confirm: bool) -> None`
- `upload_attachment(radar_id, path, *, confirm: bool) -> None`

Writes **must** refuse when `confirm` is false (draft-only path returns preview without calling `commit_changes`).

## Stub vs live

| Backend | When |
|---------|------|
| `stub` | Default; CI; no Apple network |
| `radarclient` | Host has Kerberos ticket + `radarclient` importable; implemented in `integrations/radar/client.py` |

**Stub fixture:** offline copy of lab sample **`rdar://101493937`** (`Ruby,P0,Scarif flash erase issue` — flash erase / standby / `pwr_state set factory`, real attachment names from `radar.log`). Prefer that id in Open WebUI smoke. Other radar ids reuse the same narrative; `fa.radar.stub_component_*` only remaps component for non-canonical ids (EE-Wiki scope tests).

Live mapping is covered by `integrations/radar/map_problem.py`.

## Security

- Credentials only via environment / OS Kerberos cache — never in YAML committed to git
- Log Radar ids and high-level actions; do not log full diagnosis bodies at info level in shared logs if policy requires
- Confirm gate is mandatory for any mutating tool exposed to agents / chat

## Related

- [fa-session.md](fa-session.md)
- [integrations-flames.md](integrations-flames.md)
- Protocol: `src/ee_wiki/protocols/radar.py`
- Stub: `src/ee_wiki/integrations/radar/`
