# 0009. Multi-source Schematic Connectivity Map

Date: 2026-07-18
Status: accepted

## Context

[ADR 0007](0007-schematic-connectivity-extraction.md) defined a page-level evidence ladder (CAD netlist → PDF geometry → OCR spatial) with winner-take-all selection. Operators commonly place under `sch/` (or `sch/cad/`):

1. One or more schematic **PDF**s (always for this pipeline)
2. Optional Landrex/TestLink **BoardView** `.brd` (logical pin↔net; not Gerber copper)
3. Optional schematic **netlist** (`.net`, KiCad, Altium exports, …)

These sources are complementary: netlist/boardview supply electrical pin–net truth; PDF supplies page/module spatial context and narrative. Missing companions must not fail ingest.

ADR 0007 listed Gerber/PCB copper as out of scope. Landrex BoardView is **not** copper — it is a pin–net boardview suitable as connectivity evidence.

## Decision

### 1. Complementary merge (not winner-take-all)

Parse every available companion independently. Merge into one document-level map with per-binding `evidence` tags. On conflicting `(refdes, pin)` → `net` assignments, higher priority overwrites; lower priority only fills gaps.

| Priority | Evidence tag | Source |
|----------|--------------|--------|
| 1 | `cad_netlist` | Companion netlist parser succeeds |
| 2 | `boardview` | Landrex/TestLink `.brd` (decrypt + Parts/Pins) |
| 3 | `pdf_geometry` | Per-page connector catchment (ADR 0007) |
| 4 | `ocr_spatial` | Per-page OCR proximity (ADR 0007) |

Absent file or unsupported format → empty layer + structured log; continue.

Priority here is **merge-fill order only**; trace *authority* is governed solely
by `connectivity.authoritative_evidence` (§5) — currently `cad_netlist` alone.

### 2. Discovery (once per PDF)

Same search order as ADR 0007, with extensions grouped by kind in config:

- `companion_extensions.netlist` — `.net`, KiCad, Altium suffixes
- `companion_extensions.boardview` — `.brd`

Legacy `cad_extensions` remains accepted as an alias for netlist suffixes.

### 3. Sidecar schema v2

Write `*.connectivity.json` with additive document-level `nets` / `parts` plus existing `pages[]`:

```json
{
  "schema_version": 2,
  "source_file": "...pdf",
  "companions": {"netlist": "...|null", "boardview": "...|null"},
  "sources_used": ["boardview", "pdf_geometry"],
  "nets": {"NET": [{"refdes": "U1", "pin": "1", "evidence": "boardview"}]},
  "parts": {"U1": {"pins": [{"pin": "1", "net": "NET", "evidence": "boardview"}]}},
  "pages": []
}
```

### 4. Module boundaries

| Layer | Responsibility |
|-------|----------------|
| `connectivity/boardview/`, `connectivity/netlist/` | Format parsers behind `ConnectivityCompanionParser` |
| `connectivity/discover.py`, `merge.py` | Discovery + merge |
| `knowledge/` / `tools/` | Index / MCP over sidecar — follow-up |

### 5. Authoritative-only trace gate (answer-grade)

Evidence tags exist so answers stay honest, but a visible tag is not enough for
Failure Analysis: a half-correct trace from `pdf_geometry` / `ocr_spatial` is
worse than no answer because it silently misleads the analyst. Therefore
**answer-grade** trace (chat, MCP, HTTP, and any FA flow) is gated:

- Only `cad_netlist` (config `connectivity.authoritative_evidence`) may ground a
  returned net/pin trace. `boardview` (BoardView `.brd`) is **intentionally
  excluded** from the authoritative set: it is retained as an *advisory
  reference* (net-membership / probe-point hints) but must never ground a trace.
  BoardView is a logical pin↔net list, not copper geometry, and cannot deliver
  accurate physical track routing — so presenting it as verified trace would
  overstate its reliability (decision 2026-07-21).
- When `connectivity.require_authority_for_trace` (default `true`) and only
  advisory (boardview / geometry / OCR) evidence exists, the trace is **refused**
  (`authority = "insufficient"`), not returned. Advisory data is surfaced
  separately under `advisory_pins` / `advisory_connectors` for transparency.
- `module_nets` is a page **locator**, not a trace; it is always tagged
  `authority = "advisory"` and never presented as verified connectivity.
- Enforcement lives at the single core choke point
  `ConnectivityQuery.resolve_trace` (`connectivity/authority.py`), so every
  consumer — including the chat trace intercept and any future FA/ToolBus
  auto-trace — inherits the gate. Raw `trace_net` / `connector_pins` /
  `module_nets` stay unfiltered for low-level use.

### 6. Out of scope

- Allegro proprietary binary `.brd`, Gerber copper
- HTTP/MCP trace APIs (sidecar is the contract)
- Cross-stem multi-PDF board assembly
- Cloud image-to-netlist

## Consequences

### Positive

- PDF-only, PDF+BRD, PDF+netlist, or all three share one ingest path
- Evidence tags keep RAG honest about netlist vs boardview vs geometry
- New formats plug in via protocol + registry without changing chat contracts

### Negative / limits

- BoardView pin numbers are ordinal within a part when the format has no pin name
- Stub parsers (KiCad schematic, Altium project) log and return `None` until implemented

### Follow-ups

- Full KiCad / Altium netlist parsers
- ~~MCP `trace_net` / `connector_pins` over v2 sidecar~~ — done: `src/ee_wiki/connectivity/` + `GET /v1/schematic/connectivity/*` + MCP `trace_net_tool` / `connector_pins_tool` / `module_nets_tool`
- ~~Authoritative-only trace gate for FA-grade answers~~ — done: `connectivity/authority.py` + `ConnectivityQuery.resolve_trace` + chat trace intercept (`connectivity/chat.py` / `connectivity/intent.py`); config `connectivity.authoritative_evidence` / `require_authority_for_trace`
- Feed `cad_netlist` / `boardview` bindings into V3 graph edges
