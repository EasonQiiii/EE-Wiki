# Knowledge Authoring Guide

How to write and place documents in EE-Wiki so retrieval and RAG answers work well.

**Use this file with an AI assistant:** attach this guide plus your draft (notes, exports, chat logs, messy Word/Markdown). Ask the AI to **reformat the draft to match this spec** and output files ready for `data/raw/` with the correct path.

After authoring:

```bash
python scripts/sync.py data/raw/<target-path>/
```

See [ingest.md](ingest.md) for the ingest pipeline.

---

## Quick decision: where does this document go?

```
Is it shared by ALL projects (tools, industry terms, generic datasheets)?
  └─ YES → data/raw/global/{type}/<file>
  └─ NO  → Is it shared by ALL builds in ONE project?
            └─ YES → data/raw/{project}/common/{type}/<file>
            └─ NO  → data/raw/{project}/{build}/{type}/<file>
```

| Layer | Path | `project` / `build` metadata | What belongs here |
|-------|------|------------------------------|-------------------|
| **Global** | `global/{type}/` | `global` / `global` | Industry background, company-wide acronym glossaries, generic tool usage, common component datasheets, enterprise FA methods — **not** board-specific wiring |
| **Project common** | `{project}/common/{type}/` | `{project}` / `common` | That product's architecture, naming rules, shared IP description, cross-build bring-up — **not** pin/net facts for one revision |
| **Build** | `{project}/{build}/{type}/` | `{project}` / `{build}` | Schematics, build-specific SOPs, debug notes, BOM context for **one hardware revision** |

**Do not** put large factual knowledge in `prompts/` — prompts hold *how to answer* rules; facts belong in `data/raw/` and are retrieved on demand (only relevant chunks enter the LLM context).

---

## Document type folders (`{type}`)

| Folder | `document_type` | Use for |
|--------|-----------------|---------|
| `note/` | `engineering_note` | Notes, glossaries, background, debug write-ups, architecture prose |
| `sop/` | `sop` | Procedures, checklists, bring-up flows |
| `sch/` | `schematic` | Schematic PDFs (VLM ingest) |
| `datasheet/` | `datasheet` | Component datasheet PDFs (VLM ingest under `datasheet/`) |
| `fa/` | `failure_analysis` | RMA reports, 8D, FA summaries, defect analysis write-ups — prefer structured debug-case fields (below) |

**Authoring tip:** industry acronyms, product lifecycle (EVT/DVT/PVT), and general EE background → prefer `global/note/` (split into focused files, see below).

### Debug cases (`fa/`) — V3 P2

Structured fields improve case lookup and graph links. Prefer YAML frontmatter **or** clear Markdown headings:

```markdown
---
case_id: RMA-2024-001
symptom: No boot after power cycle
suspected_nets: [NET_VCC, PWR_EN]
suspected_parts: [U101, TPS61299]
steps:
  - Measure VCC at U101 pin 3
  - Check EN assertion timing
root_cause: Open solder joint on U101 pin 3
citations:
  - logan/p1/sch/power.md
---

# RMA-2024-001 No-boot FA

Narrative and evidence…
```

Heading aliases also work (`## Symptom`, `## Suspected Nets`, `## Suspected Parts`, `## Steps`, `## Root Cause`). After ingest + index, cases appear in `data/indexes/cases.json` and as Case nodes when you run `python scripts/build_graph.py`.

---

## Path and filename rules

- Path must match: `data/raw/{project}/{build}/{type}/<filename>`
- Use lowercase project/build segments (e.g. `logan`, `p1`, `common`, `global`).
- Prefer descriptive filenames: `acronym-glossary-networking.md`, not `notes1.md`.
- One main topic per file when possible — helps chunking and retrieval.
- Supported text formats: `.md`, `.markdown`, `.txt`, `.pdf`, `.xlsx`, `.doc`, `.docx`.

Examples:

```text
data/raw/global/note/product-lifecycle-builds.md
data/raw/global/note/acronym-glossary-power.md
data/raw/logan/common/note/naming-conventions.md
data/raw/logan/p1/note/comm-interface-bringup.md
data/raw/logan/p1/sch/main-board.pdf
data/raw/global/datasheet/LAN8720A.pdf
```

---

## Markdown structure (for good chunking)

EE-Wiki chunks by headings (`#`, `##`) with a target of ~1500 characters per chunk. Write so each section can stand alone.

### Required habits

1. **Title** — start with a single `#` document title.
2. **Sections** — use `##` for major sections; `###` for subsections.
3. **Atomic sections** — one concept per `##` block (one acronym entry, one lifecycle stage, one procedure).
4. **Retrieval keywords** — in the first line of a section, include terms users might search (full name, abbreviation, Chinese if used in your org).
5. **Code blocks** — use fenced ` ``` ` for commands; do not break fences mid-block.
6. **No huge single files** — split glossaries by domain (networking, power, manufacturing).

### Acronym / term entry template

```markdown
## RMII (Reduced MII)

**Also known as:** Reduced Media Independent Interface, 精简 MII

**Category:** networking, PHY/MAC interface

**Definition:** …

**Typical use:** …

**Related terms:** MII, RGMII, MDIO, PHY

**See also:** `data/raw/global/datasheet/LAN8720A.pdf` (if applicable)
```

### Product lifecycle / build stage template

```markdown
## DVT (Design Validation Test)

**Stage order:** EVT → DVT → PVT → MP (adjust to your org)

**Purpose:** …

**Typical deliverables:** …

**Common documents at this stage:** schematic revision, bring-up SOP, …
```

### Engineering note template

```markdown
# {Short title}

**Scope:** global | logan / common | logan / p1  
**Last updated:** YYYY-MM-DD  
**Owner:** team or name (optional)

## Summary

One paragraph: what this document is for.

## …

(Content sections with ## headings)
```

The `**Scope:**` line is for human readers; ingestion derives scope from the **file path**, not from this line. Place the file in the path that matches the real scope.

### SOP template

```markdown
# {Procedure name}

**Applies to:** logan / p1 (or logan / common, or global)

## Prerequisites

## Steps

1. …
2. …

## Verification

## Troubleshooting
```

---

## What goes in `global/note/` (industry background)

Put here (as separate Markdown files):

- Acronym and abbreviation glossaries (split by topic)
- Product lifecycle and build-phase definitions (EVT, DVT, PVT, etc.)
- Industry practices and generic tool usage (oscilloscope, power supply, fixture concepts)
- Enterprise-wide engineering conventions

Do **not** put here:

- Board-specific net names, pin maps, or schematic facts → `{project}/{build}/`
- One product line's internal codenames only that team uses → `{project}/common/`

Retrieval loads only **relevant** chunks into the LLM — a 500-term glossary does not consume context on every question.

---

## Query scope vs. document placement (for authors)

| User query | What gets searched | How answers should read |
|------------|-------------------|-------------------------|
| `project=logan`, `build=p1` | `logan/p1` → `logan/common` → `global` | Build conclusions first; label **project common** and **global** separately |
| `project=logan`, `build=common` | `logan/common` → `global` only | No p1/p2 build-specific docs |
| No project/build | Entire index | Answer **by scope**; recommend specifying build for board-level facts |

Authors should write build-specific facts only under `{project}/{build}/` so they are not mistaken for global truth.

---

## AI reformattask checklist

When asking an AI to clean up a messy source file, provide:

1. This guide (`docs/usage/knowledge-authoring.md`)
2. The raw draft (any format)
3. Explicit instructions, for example:

> Reformatt the attached draft into one or more EE-Wiki Markdown files per `knowledge-authoring.md`.  
> Tell me the exact `data/raw/...` path for each output file.  
> Split glossaries by topic. Use ## per term or per lifecycle stage.  
> Do not invent hardware facts; preserve only what is in the draft; mark gaps as TBD.

### Output the AI should deliver

- [ ] One or more `.md` files with `#` title and `##` sections
- [ ] Proposed path under `data/raw/` for each file
- [ ] Scope stated: global / project common / build
- [ ] Search-friendly headings (full name + abbreviation)
- [ ] No content that belongs in prompts or code

### Author review before ingest

- [ ] Path matches content scope (global vs common vs build)
- [ ] Filenames are descriptive
- [ ] Large glossaries split into multiple files
- [ ] Sensitive or customer-specific paths are acceptable for your repo policy
- [ ] Run `python scripts/sync.py data/raw/<path>/` (or `POST /v1/ingest` — see [mcp.md](mcp.md))

---

## Related docs

- [ingest.md](ingest.md) — ingest CLI and formats
- [mcp.md](mcp.md) — V2 re-sync, HTTP ingest, component lookup
- [README — Raw Data Layout](../../README.md#raw-data-layout)
- [README — Retrieval Scope & answer presentation](../../README.md#retrieval-scope)
- [query.md](query.md) — testing retrieval with `--project` / `--build`
- [AGENTS.md](../../AGENTS.md) — platform rules for coding agents
