# Agent runtime (V4 / ADR 0008)

EE-Wiki chat uses a **Supervisor + ToolBus + config-driven specialists** when `agents.enabled` is true (default).

## Routing order (ADR 0012)

1. FA check-in / evidence (`帮我FA一下radar://…`, `rdar://…`, …) — chat
   `pre_rag_gates()` once
2. Authoritative connectivity / trace (CAD netlist / BoardView only) — same gates
3. **Rules-first** role-pack keywords (`route_score_threshold`); if roles clear →
   skip routing LLM
4. Else local-LLM semantic route selects `TASK` + up to `max_roles_per_turn`
   specialists (`fa`, `hw`, `power`, `pcb`, `si`, `mfg`)
5. Specialists → fuse evidence → **hybrid RAG** (`RagService`) with citations;
   empty evidence still falls through to retrieve (no evidence-only
   `stream_direct`)
6. No specialists → passthrough hybrid RAG with supervisor `TASK`

FA and connectivity remain deterministic hard gates; the LLM cannot bypass their
ID or authority requirements. When the supervisor owns the turn,
`generation.task_classification` is treated as off for that request
(`task_owner=supervisor`). Legacy classify remains for `agents.enabled: false`.

Look for `RequestTrace` log lines (`gate=`, `route_mode=`, `branch=`, `phase_ms=`)
to verify which path ran.

Roles live under `config/agents/roles/*.yaml`. Lab tuning = edit YAML keywords
(fallback), recipe, or tool allowlists — no Python changes required. Invalid
packs fail at load time.

## Kill switch

```yaml
agents:
  enabled: false
```

Falls back to the pre-V4 FA → trace → RAG cascade.

## Lab readiness checklist

Framework code is already in the repo. Lab work needs **data + models + a short smoke**,
not more Python modules. Use this as the on-site packing list.

### Runtime (usually already set)

| Item | Notes |
|------|--------|
| `.env` from `.env.example` | Export `EE_WIKI_DATA_DIR`, `EE_WIKI_MODELS_DIR` (shell export; repo does not auto-load `.env`) |
| Models under `EE_WIKI_MODELS_DIR` | Names match `config/default.yaml` → `models.*` (embedding, reranker, MLX LLM) |
| `agents.enabled: true` | Default in `config/default.yaml`; set `false` only to fall back |

See [local-setup.md](local-setup.md) for Apple Silicon / multi-user LLM details.

### Knowledge under `data/raw/`

For at least one real `{product}/{project}/{build}` (ADR 0011):

```text
data/raw/{product}/{project}/{build}/sch/     # schematic PDF(s)
data/raw/{product}/{project}/{build}/note/    # bring-up / design notes
data/raw/{product}/{project}/{build}/sop/     # optional
data/raw/{product}/{project}/{build}/fa/      # optional historical FA
data/raw/{product}/{project}/common/...       # project-wide shared
data/raw/{product}/common/...                 # product-wide shared
data/raw/global/...                           # enterprise shared
```

If raw trees are still two-level (`data/raw/{project}/...`), run the layout
migration first (dry-run → `--apply`), then delete/recreate processed+indexes+graph
and re-ingest — see [ingest.md](ingest.md#adr-0011-layout-migration).

Then ingest + index (or `scripts/sync.py`). Path rules: [knowledge-authoring.md](knowledge-authoring.md), [ingest.md](ingest.md).

### Connectivity companions (required for FA-grade trace)

Same stem as the schematic PDF, under `sch/` or `sch/cad/`:

| File | Role |
|------|------|
| `*.net` (or KiCad / Altium companion) | Authoritative netlist (`cad_netlist`) |
| `*.brd` | BoardView (`boardview`) |

Without these, chat/MCP/FA **refuse** pin–net answers instead of guessing (ADR 0009).
PDF / OCR alone never counts as board-verified electrical truth.

### FA session extras

| Item | Notes |
|------|--------|
| `assets/templates/fa/one_page.key` | Company one-page Keynote template for exports; see [assets/templates/fa/README.md](../../assets/templates/fa/README.md) |
| Radar / Flames backends | Default `stub` / `manual` — enough to exercise check-in without live credentials |

### Minimal pack before first smoke

1. One `sch/*.pdf` + same-stem `.net` and/or `.brd`
2. A few `note/` / `sop/` docs so power / hw specialists have retrieval fodder
3. Ingest + index completed for that scope
4. Run the utterances below

## Manual smoke (lab)

| Utterance | Expect |
|-----------|--------|
| `帮我FA一下radar://123456` | FA check-in stub (not a RAG essay) |
| `trace net EDP_AUXP` (no companion) | Authoritative refusal |
| `trace net <known net>` (with `.net` / `.brd`) | Authoritative pins / net answer |
| `VDD_1V8 电源轨从哪里来` | power role evidence → grounded answer |
| casual chat | passthrough RAG |
| `agents.enabled: false` | legacy cascade |
