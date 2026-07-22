# Agent runtime (V4 / ADR 0008)

EE-Wiki chat uses a **Supervisor + ToolBus + config-driven specialists** when `agents.enabled` is true (default) for **WikiMode**. **FaMode** is a case-centric **FaAgent** on the **same ToolBus** — Radar optional at entry (intent or `radar://`); see [fa-session.md](../architecture/fa-session.md).

## Dual-mode flow（目标）

```text
Open WebUI → EE-Wiki /v1/chat/completions
        │
        ├─ FaMode  if radar:// | FA session bound | FA调查意图(LLM mode classify)
        │     FaAgent → skills → ToolBus（Radar / Flames / trace / case…）
        │     → EvidenceBundle → 生成（事实必须有 provenance）
        │     无票：**FA（未绑定 Radar）：** <symptom>（一行可读头，scope 走不可见 marker）；有票后再 bind
        │
        └─ WikiMode（默认）
              Supervisor → clarify | passthrough | hybrid RAG + citations
```

工具实现只维护一份；FaAgent / 未来 FbAgent = 不同 allowlist，不复制 handlers。

施工单：[fa-agent-implementation-plan.md](../architecture/fa-agent-implementation-plan.md)。

## WikiMode routing（ADR 0012 — Supervisor-first）

1. **Supervisor** (always when `agents.enabled`) — `clarify` | `respond` | `passthrough` | `hybrid`
2. **Rules-first** role-pack keywords (`route_score_threshold`); if roles clear → skip routing LLM
3. Else local-LLM semantic route selects `TASK` + up to `max_roles_per_turn`
   specialists (`radar`, `fa`, `hw`, `power`, `pcb`, `si`, `mfg`)
4. Specialists → fuse evidence → **hybrid RAG** (`RagService`) with citations;
   empty evidence still falls through to retrieve (no evidence-only `stream_direct`)
5. No specialists → passthrough hybrid RAG with supervisor `TASK`

FA check-in today still enters via Supervisor → `radar` role (migration toward FaAgent in [fa-session.md](../architecture/fa-session.md)). Authoritative connectivity remains ToolBus `trace_net` / `connector_pins` (ADR 0009). When the supervisor owns a Wiki turn, `generation.task_classification` is off (`task_owner=supervisor`). Legacy classify remains for `agents.enabled: false`.

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

For a full reading order and role split for colleagues joining lab, see
[lab-handoff.md](lab-handoff.md).

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
| `*.brd` | BoardView (`boardview`) — advisory reference only, not a trace source |

Without a CAD netlist, chat/MCP/FA **refuse** pin–net answers instead of guessing
(ADR 0009). BoardView (`.brd`) is retained for net-membership / probe-point
reference but never grounds a trace. PDF / OCR alone never counts as board-verified
electrical truth.

**Ingest path:** schematic PDF parse discovers companions → parses `.net` (generic
line-oriented / light KiCad sexpr; Altium/KiCad project files are stubs) and
`.brd` (Landrex BoardView) → merges into `*.connectivity.json` next to processed
markdown when `write_sidecar: true`. Re-ingest after adding companions.

`scripts/serve.py` (and API startup) logs **WARNING**s for missing `.net`,
unparsed netlists, missing sidecars, empty `sop/`, missing indexes, and FA Keynote
template gaps — see `ee_wiki.api.startup_checks.warn_lab_readiness`.

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
| `帮我FA一下为什么U8600（logan p1）的IIC接口没有输出` | **FaMode unbound**（一行 `**FA（未绑定 Radar）：**` 头，非纯 wiki RAG，不再贴原始工具 JSON） |
| `radar://101493937` | FaMode 有票 check-in（Scarif stub）；可无票会话上 bind |
| `STM32F407 核心参数` | WikiMode（非 FA） |
| `帮我看看` | WikiMode → `clarify`（或等价追问） |
| `J1 第3脚连到哪` (no scope) | clarify 要 scope（Wiki 或 FA 内均可，勿静默瞎追网） |
| `trace net EDP_AUXP` (no companion, with scope) | tool reject（权威不足） |
| `VDD_1V8 电源轨从哪里来` | WikiMode → power → `hybrid` |
| casual chat | passthrough RAG |
| `agents.enabled: false` | legacy cascade |
