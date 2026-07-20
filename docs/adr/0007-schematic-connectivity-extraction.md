# 0007. Schematic Connectivity Extraction (CAD-first, PDF geometry fallback)

Date: 2026-07-14
Status: accepted

## Context

Schematic ingest today binds nets to module zone labels using OCR word boxes and reading-order proximity ([signals.py](../../src/ee_wiki/ingestion/parsers/schematic_pdf/signals.py)). That is good enough for many pin questions but is **not electrical connectivity** — dense pages still mis-attribute nets, and OCR-only evidence cannot prove a connector pin list.

Operators typically have:

1. **Native CAD / netlist** beside or instead of the PDF (KiCad `.net` / `.kicad_sch`, Altium exports, etc.) when the design is still in EDA.
2. **Vector PDF schematics** (common Altium/OrCAD printouts) with recoverable line geometry and text — no Gerber required for schematic pin questions.

[ADR 0006](0006-knowledge-graph-store.md) deliberately left **full CAD netlist import** out of the knowledge-graph store. Connectivity extraction belongs in **ingestion**, writing structured sidecars that indexing and (later) graph/MCP can consume.

Constraints from AGENTS.md:

- Offline first — no cloud schematic-to-netlist SaaS
- No project-specific parsers or hardcoded part numbers in `src/`
- Parser never retrieves or generates final answers
- Prefer config (`data_layout`, `ingestion.schematic_pdf`) over code branches

## Decision

### 1. Evidence ladder (highest wins)

When building per-page module↔net bindings for schematic ingest:

| Priority | Source | Evidence tag | When |
|----------|--------|--------------|------|
| 1 | Companion CAD / netlist next to the PDF (or under the same `sch/` folder) | `cad_netlist` | File present and parser succeeds |
| 2 | PDF vector geometry: connector designators (`P8`, `J1`, …) as catchment, nets nearest that connector, connector linked to nearest module zone label | `pdf_geometry` | PDF has drawings + OCR tokens |
| 3 | Existing OCR spatial / reading-order association | `ocr_spatial` | Fallback |

Answers and retrieval chunks must keep the evidence tag visible in the OCR fidelity / connectivity appendix so the LLM does not treat geometry guesses as netlist truth.

### 2. Module boundary

| Layer | Responsibility |
|-------|----------------|
| `ingestion/parsers/schematic_pdf/connectivity/` | Discover CAD companions, PDF geometry catchment, merge bindings into fidelity Markdown / sidecar |
| `knowledge/` | Index connectivity fields on chunks when present (same as other sidecar metadata) |
| `tools/` / `api/` | Optional later read-only MCP/HTTP (`connector_pins`, `module_nets`) over indexed sidecars — not in this ADR’s mandatory scope |
| `generation/` | No direct CAD/PDF geometry access |

### 3. Companion CAD discovery (no hardcoded project names)

Configured extensions under `ingestion.schematic_pdf.connectivity.cad_extensions`, searched in this order:

1. Same directory, same stem as the schematic PDF (`Board.pdf` → `Board.net`)
2. Same directory, any matching extension (first parseable wins)
3. Optional: `sch/cad/` sibling folder (same stem)

Unsupported formats log and fall through to PDF geometry — do not fail ingest.

### 4. PDF geometry method (phase 1)

Phase 1 does **not** require full wire skeletonization:

- Detect connector-like designators with a structural regex (`P`/`J`/`CN`/`CON`/`HDR` + digits)
- Assign each OCR net name to the **nearest** connector center within a configured max distance
- Assign each connector to the **nearest** module zone label (prefer labels above the connector)
- Union nets per module; emit `### 模块：` blocks with evidence note `pdf_geometry`

Full wire-segment union-find remains a follow-up if catchment misses multi-connector buses.

### 5. Sidecar

Write `*.connectivity.json` next to the processed `.md` (mirroring raw path under `data/processed/`), optional and additive — missing sidecar must not break V2/V3 consumers.

Schema (conceptual):

```json
{
  "source": "pdf_geometry",
  "pages": [
    {
      "page": 3,
      "connectors": [{"refdes": "P8", "module": "OLED&CAMERA", "nets": ["DCMI_D0", "..."]}],
      "module_nets": {"OLED&CAMERA": ["DCMI_D0", "..."]}
    }
  ]
}
```

### 6. Out of scope

- Gerber / PCB copper connectivity (board-level; separate ADR if needed)
- Cloud image-to-netlist services
- Manual pin-map authoring as a required path
- Replacing VLM narrative pages (geometry/CAD enrich the OCR fidelity appendix only)

## Consequences

### Positive

- Clear upgrade path when CAD appears without changing chat/retrieval contracts
- Immediate quality lift on vector PDF connector pages without human sidecars
- Evidence tags keep RAG honest about CAD vs geometry vs OCR

### Negative / limits

- Connector catchment is still geometric, not guaranteed electrical connectivity
- Designs without `P`/`J` headers rely on CAD or OCR spatial fallback
- KiCad/Altium parsers land incrementally behind the discovery interface

### Follow-ups

- ~~KiCad `.net` / `.kicad_sch` parsers behind `CadNetlistParser` protocol~~ — superseded by [ADR 0009](0009-multi-source-schematic-map.md) (`ConnectivityCompanionParser` + multi-source merge; KiCad/Altium still stubbed)
- Optional wire-graph phase 2 for non-connector nets
- MCP `connector_pins` / `module_nets` reading the connectivity sidecar
- Feed `cad_netlist` bindings into V3 graph build as first-class edges

**Superseded for companion scope:** document-level PDF + BoardView `.brd` + netlist complementary map — see [ADR 0009](0009-multi-source-schematic-map.md). Page-level PDF geometry / OCR spatial rules in this ADR remain in force.
