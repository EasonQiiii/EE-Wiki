# Ingest Guide

How to run `scripts/ingest.py` — the raw → processed pipeline for EE-Wiki.

## Prerequisites

```bash
cd /path/to/EE-Wiki
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

Copy and adjust environment (optional):

```bash
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `EE_WIKI_DATA_DIR` | Data root (default: `./data`) |
| `EE_WIKI_MODELS_DIR` | Local models (default: see `.env.example`) |

Schematic PDF parsing depends on `ingestion.schematic_pdf.fidelity_mode`:

| Mode | Models | When to use |
|------|--------|-------------|
| **`ocr_only` (default)** | none for vision — PyMuPDF OCR text only | FA / ingest speed; pin–net truth comes from CAD netlist (`.net` / KiCad / Altium); `.brd` is advisory reference only (ADR 0009) |
| `vlm_plus_ocr` | `layoutlmv3-base` + `Qwen3-VL-*` | Optional schematic prose for RAG recall (slow) |

Datasheet PDFs under `datasheet/` still use the datasheet VLM pipeline when pages are table/graph/mixed. Markdown / TXT need no models.

## Where to put raw files

Place documents under `data/raw/` using the three-level layout (see [Raw Data Layout](../../README.md#raw-data-layout) and [ADR 0011](../adr/0011-product-project-build-hierarchy.md)):

```
data/raw/
├── global/                         # enterprise-wide shared
├── {product}/                      # e.g. iphone
│   ├── common/                     # product common (all projects)
│   └── {project}/                  # e.g. logan
│       ├── common/                 # project common (all builds)
│       └── {build}/                # e.g. p1
│           ├── note/               # engineering notes (.md, .txt)
│           ├── sch/                # schematics (.pdf)
│           └── sop/                # SOPs
```

### Where to put a document

| Put it under | When |
|--------------|------|
| `global/{type}/` | Shared by **all products** — generic tool guides, industry practices, common component datasheets |
| `{product}/common/{type}/` | Shared by **all projects in that product** — platform architecture, naming, cross-project SOPs |
| `{product}/{project}/common/{type}/` | Shared by **all builds in that project** — program-wide knowledge, not board wiring |
| `{product}/{project}/{build}/{type}/` | Specific to **one hardware revision** — schematics, build debug notes, that build's procedures |

See [README — Retrieval Scope](../../README.md#retrieval-scope) for how retrieval and answers treat each layer.

### ADR 0011 layout migration

Legacy trees used two levels (`data/raw/{project}/...`). After ADR 0011 they must
live under `data/raw/{product}/{project}/...`. Use the dry-run-first CLI:

```bash
# Dry-run (default): print planned moves only
python scripts/migrate_raw_layout.py --map logan=iphone,macon=iphone

# Or load the map from YAML/JSON
python scripts/migrate_raw_layout.py --map-file path/to/map.yaml

# Execute moves
python scripts/migrate_raw_layout.py --map logan=iphone,macon=iphone --apply
```

Safety rules:

- Mapping is **required** (CLI `--map` and/or `--map-file`)
- `data/raw/global/` is never moved
- Reserved names `global` / `common` are rejected as ordinary product or project slugs
- Destination collisions and nesting into another legacy project tree are refused
- **Only** `data/raw/` project trees are moved — not `data/processed/`, `data/indexes/`,
  `data/graph/`, or FA cache/exports (those stay Radar-keyed)

**Cutover after `--apply`:**

1. Migrate raw (commands above)
2. Delete / recreate `data/processed/`, `data/indexes/`, and `data/graph/`
3. Re-ingest, re-index, rebuild the graph:

```bash
rm -rf data/processed data/indexes data/graph
mkdir -p data/processed data/indexes data/graph
python scripts/ingest.py --force
python scripts/index.py --force
python scripts/build_graph.py
# or: python scripts/sync.py --force && python scripts/build_graph.py
```

For **how to write** Markdown (glossaries, lifecycle docs, templates for AI reformatting), see [knowledge-authoring.md](knowledge-authoring.md).

Supported formats (V1):

| Folder | Formats |
|--------|---------|
| `note/`, `sop/`, `datasheet/`, etc. | `.md`, `.markdown`, `.txt`, `.pdf` (text + OCR), `.xlsx`, `.doc`, `.docx`, `.key`, `.numbers` (macOS) |
| `sch/` | `.pdf` (schematic vision pipeline); optional same-stem companions: `.brd` (BoardView, advisory reference), `.net` / KiCad / Altium (netlist, authoritative) — see ADR 0009 |
| `datasheet/` | `.pdf` (datasheet VLM pipeline when under `datasheet/`; prose PDF + OCR otherwise) |
| `fa/` | `.md`, `.txt`, `.pdf`, `.doc`, `.docx` (failure analysis reports) |

Prose PDFs (`note/`, `sop/`, `datasheet/`, …) extract embedded text per page. Pages with little selectable text fall back to **Tesseract OCR** via PyMuPDF. Install Tesseract locally for scanned documents:

```bash
# macOS
brew install tesseract tesseract-lang

# Debian/Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-chi-sim
```

OCR language defaults to **`auto`** (`ingestion.prose_pdf.ocr_language`):

| Situation | Behavior |
|-----------|----------|
| Embedded text contains Chinese | Uses `eng+chi_sim` |
| Embedded text is Latin only | Uses `eng` |
| Image-only scan | Tesseract OSD on page 1, then `ocr_language_fallback` (`eng+chi_sim` by default) |
| Mixed pages in one PDF | Per-page override when a sparse page still has CJK/Latin hints |

Set `ocr_language: eng` or `eng+chi_sim` to force a fixed language pack. Tune `min_text_chars`, `ocr_dpi`, and `ocr_language_fallback` in `config/default.yaml` → `ingestion.prose_pdf`.

### Word (`.doc` / `.docx`)

Word documents in `note/`, `sop/`, `datasheet/`, etc. are converted to Markdown under `data/processed/`.

| Format | Parser | Dependency |
|--------|--------|------------|
| `.docx` | `mammoth` (pure Python) | `pip install -e ".[dev,ml]"` |
| `.doc` (legacy) | LibreOffice → PDF → prose PDF pipeline | [LibreOffice](https://www.libreoffice.org/) installed locally |

Install Python extras (includes `mammoth`):

```bash
pip install -e ".[dev,ml]"
```

Install LibreOffice for legacy `.doc` files:

```bash
# macOS
brew install --cask libreoffice

# Debian/Ubuntu
sudo apt install libreoffice
```

Verify `soffice` is available:

```bash
soffice --version
# or on macOS:
/Applications/LibreOffice.app/Contents/MacOS/soffice --version
```

If LibreOffice is not on `PATH`, set one of:

- Environment: `EE_WIKI_LIBREOFFICE_PATH=/path/to/soffice`
- Config: `ingestion.word.libreoffice_path` in `config/default.yaml`

Legacy `.doc` files are converted to PDF headlessly, then text is extracted with the same prose PDF logic (embedded text + Tesseract OCR fallback for scanned pages). Chinese datasheets benefit from the same `ocr_language: auto` settings as PDFs.

### Apple iWork (`.key` / `.numbers`, macOS only)

On macOS with Keynote and Numbers installed, EE-Wiki exports iWork files before parsing:

| Format | Export | Parser |
|--------|--------|--------|
| `.key` | PDF via Keynote (AppleScript) | Prose PDF pipeline |
| `.numbers` | `.xlsx` via Numbers (AppleScript) | Excel pipeline |

Config: `config/default.yaml` → `ingestion.iwork` (`enabled`, export timeouts, `quit_apps_after_export`).

Requirements:

- macOS with **Keynote** and **Numbers** (App Store or iWork)
- **Automation** permission for Terminal or your Python process (System Settings → Privacy & Security → Automation)
- A logged-in GUI session (export is not headless; Keynote/Numbers may open briefly)

On Linux or when `ingestion.iwork.enabled: false`, `.key` and `.numbers` are skipped with a warning. See [ADR 0004](../adr/0004-iwork-macos-export.md).

## Basic command

From the repository root:

```bash
python scripts/ingest.py
```

With no arguments, this:

1. Walks **all** of `data/raw/`
2. **Ingests** new or changed files into `data/processed/`
3. **Skips** unchanged files (see [Incremental ingest](#incremental-ingest))
4. **Removes** processed `.md` / `.meta.json` whose raw source was deleted

## All usage modes

### Full sync (recommended for daily use)

```bash
python scripts/ingest.py
```

- Scope: entire `data/raw/`
- Cleanup: removes orphaned files under all of `data/processed/`

### Ingest one subdirectory

```bash
python scripts/ingest.py data/raw/iphone/logan/p1/
```

- Scope: all ingestible files under that directory
- Cleanup: only within the matching `data/processed/iphone/logan/p1/` subtree

### Ingest a single file

```bash
python scripts/ingest.py data/raw/iphone/logan/p2/sch/board.pdf
python scripts/ingest.py data/raw/iphone/logan/p2/note/bringup.md
```

- Scope: that file only
- Cleanup: **disabled** (other processed files are not touched)

Use this when you want to re-run one document without scanning the full tree.

### Force re-ingest

```bash
python scripts/ingest.py --force
python scripts/ingest.py data/raw/iphone/logan/p1/note/ --force
```

Ignores `source_mtime` / `source_size` in existing sidecars and re-processes every file in scope.

### Verbose logging

```bash
python scripts/ingest.py -v
python scripts/ingest.py data/raw/iphone/logan/p1/sch/board.pdf --verbose
```

Sets EE-Wiki log level to DEBUG (useful for transformers load details). Schematic PDF ingest always logs page progress at INFO. Default `ocr_only`:

```
INFO  Ingesting: acme/demo/p2/sch/board.pdf
INFO  Schematic PDF board.pdf: pipeline for 5 page(s) (fidelity_mode=ocr_only)
INFO  Schematic PDF board.pdf: page 1/5 — OCR fidelity
```

With `fidelity_mode: vlm_plus_ocr`, expect LayoutLM + VLM heartbeats (slow):

```
INFO  Schematic PDF board.pdf: pipeline for 5 page(s) (fidelity_mode=vlm_plus_ocr)
INFO  Schematic PDF board.pdf: page 1/5 — layout analysis
INFO  Schematic PDF board.pdf: page 1/5 — VLM reconstruction
INFO  Vision inference started: page 1 (image 4960x3508, 2.1 MB)
INFO  Vision inference page 1 still running (30s elapsed)
INFO  Vision inference finished: page 1 in 842.3s (1523 output tokens)
```

Long-running vision inference emits a heartbeat every 30 seconds so a silent terminal does not look hung.

## Incremental ingest

Each sidecar (`.meta.json`) stores a fingerprint of the raw file:

```json
{
  "source_file": "data/raw/acme/demo/p2/note/bringup.md",
  "target_file": "data/processed/acme/demo/p2/note/bringup.md",
  "source_mtime": 1719856070.5,
  "source_size": 36941
}
```

| Field | Meaning |
|-------|---------|
| `source_file` | Original raw path (citation / provenance) |
| `target_file` | Normalized content path used for chunking and retrieval |
| `source_mtime` | Raw file modification time at last ingest |
| `source_size` | Raw file size in bytes at last ingest |

If both `source_mtime` and `source_size` match the current raw file, ingest **skips** it.

Missing sidecar, corrupt JSON, or missing fingerprint fields → file is re-ingested.

## Orphan cleanup (raw deleted)

When raw files are removed from `data/raw/`, processed outputs must not linger.

| Invoke mode | Cleanup scope |
|-------------|----------------|
| `python scripts/ingest.py` | All of `data/processed/` |
| `python scripts/ingest.py data/raw/iphone/logan/p1/` | `data/processed/iphone/logan/p1/` only |
| Single-file path | No cleanup |

Cleanup reads `source_file` from each `.meta.json`. If that raw path no longer exists, it deletes:

- the processed Markdown (e.g. `board.md`)
- the sidecar (e.g. `board.md.meta.json`)

Empty directories under `data/processed/` are pruned afterward.

After cleanup, run `python scripts/sync.py` (or `python scripts/index.py`) so deleted documents are also removed from `data/indexes/` (see [index.md](index.md)).

### Sync after deletions

When you remove files from `data/raw/`, run **sync** so processed mirrors and retrieval indexes stay aligned:

```bash
python scripts/sync.py
```

Or run the steps separately:

```bash
python scripts/ingest.py
python scripts/index.py
```

Example stderr output after deleting two raw files:

```text
# ingest.py
Ingested: 0, skipped (unchanged): 8, removed (raw deleted): 2

# index.py
Indexed: 0 document(s), skipped (unchanged): 8, removed (processed deleted): 2 → 24 chunk(s)
```

If all processed documents are removed, `index.py` clears the entire index bundle under `data/indexes/`.

## Output layout

```
data/raw/iphone/logan/p1/note/manual.pdf
    →  data/processed/iphone/logan/p1/note/manual.md
    →  data/processed/iphone/logan/p1/note/manual.md.meta.json

data/raw/iphone/logan/p1/sch/board.pdf
    →  data/processed/iphone/logan/p1/sch/board.md
    →  data/processed/iphone/logan/p1/sch/board.md.meta.json

data/raw/iphone/logan/p1/note/manual.md
    →  data/processed/iphone/logan/p1/note/manual.md
    →  data/processed/iphone/logan/p1/note/manual.md.meta.json
```

Prose PDFs (`note/`, `sop/`, `datasheet/` outside the datasheet VLM path, …) emit per-page `## Page N` sections for chunking. Schematic PDFs follow `ingestion.schematic_pdf.fidelity_mode`:

| Mode | Pipeline |
|------|----------|
| **`ocr_only` (default)** | Per-page embedded OCR → fidelity Markdown (designators / nets / module labels) + optional connectivity sidecar. **No LayoutLMv3 / Qwen3-VL.** Fast; suitable when FA relies on netlist / BoardView for traces. |
| `vlm_plus_ocr` | (1) LayoutLMv3 crop → (2) Qwen3-VL Markdown reconstruction → (3) OCR fidelity appendix; rule-based fallback if VLM fails. Slow; optional for narrative RAG recall. |

Output merges per-page reports under one `# 电子图纸分析报告：{title}` document. Metadata includes document-level `major_components`, `nets`, and `interfaces` (from OCR fidelity and/or VLM, depending on mode).

**V2 — per-page sidecar:** schematic ingest also writes a `pages` array in `.meta.json` (one entry per PDF page with that page's components/nets/interfaces). At index time the chunker attaches page-scoped metadata to each schematic chunk. Re-ingest existing `sch/` PDFs with `--force` to populate `pages`; then re-index.

**ADR 0009 — connectivity map:** when enabled, schematic ingest also writes `{stem}.connectivity.json` next to the processed `.md`. Optional companions beside the PDF (or under `sch/cad/`) are merged by evidence priority: netlist → BoardView `.brd` → PDF geometry → OCR spatial. Missing companions are skipped (ingest still succeeds). Connectivity does **not** depend on VLM — `ocr_only` still builds the sidecar. Query via `GET /v1/schematic/connectivity/{net,pins,module-nets}` or MCP tools; answer-grade traces require `cad_netlist` (authoritative gate) — BoardView `.brd` is advisory-only and no longer grounds a trace (ADR 0013 §4).

### Datasheet PDFs (`datasheet/`)

PDFs under `.../datasheet/` use the **datasheet VLM pipeline** (page classification: text / table / graph / mixed, then Qwen3-VL extraction). Config: `config/default.yaml` → `ingestion.datasheet_pdf`.

**V2 — structured metadata** (regex heuristics on merged VLM Markdown, no extra model calls):

| Field | Example |
|-------|---------|
| `supply_voltage` | `["3.3V", "2.0V-3.6V"]` |
| `pin_count` | `144` |
| `package` | `LQFP144` |
| `interfaces` | `["I2C", "SPI"]` |

These fields improve retrieval boost for spec and pinout questions. Re-ingest `datasheet/` PDFs with `--force` after upgrading to V2.

### Failure analysis (`fa/`)

Documents under `.../fa/` map to `document_type: failure_analysis` (see `data_layout.document_type_folders` in config). During ingest, FA-specific **keywords** are extracted: failure modes (`ESD`, `THERMAL_RUNAWAY`, …), symptoms (`NO_BOOT`, `INTERMITTENT`, …), and traceability tokens (`RMA:…`, `LOT:…`, `DATECODE:…`). Place RMA reports, 8D summaries, and FA write-ups under `data/raw/{product}/{project}/{build}/fa/` or `{product}/{project}/common/fa/`.

**Debug cases (V3 P2):** optional structured fields (`case_id`, `symptom`, `suspected_nets`, `suspected_parts`, `steps`, `root_cause`, `case_citations`) via YAML frontmatter or Markdown headings. These land in the processed `.meta.json`, feed `data/indexes/cases.json` at index time, and become Case graph nodes on `python scripts/build_graph.py`. See [knowledge-authoring.md](knowledge-authoring.md#debug-cases-fa--v3-p2).

### HTTP ingest (admin)

When the API server is running, you can trigger ingest + index over HTTP instead of CLI:

```bash
curl -X POST http://localhost:8080/v1/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: '"$EE_WIKI_INGEST_API_KEY" \
  -d '{"path":"iphone/logan/p1/sch","force":true,"async":true}'
```

Set `EE_WIKI_INGEST_API_KEY` when exposing the API on LAN (optional; unset = open). For large VLM batches prefer `"async": true` and poll `GET /v1/ingest/jobs/{job_id}` — see [mcp.md](mcp.md) and [api-overview.md](../architecture/api-overview.md).

## CLI summary

```bash
# stderr summary after each run:
# Ingested: 1, skipped (unchanged): 2, removed (raw deleted): 1

# stdout lists paths for newly ingested files:
# /path/to/data/processed/iphone/logan/p1/note/new.md
# /path/to/data/processed/iphone/logan/p1/note/new.md.meta.json
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| Prose PDF empty / OCR fails | Ensure tessdata exists (`ls /opt/homebrew/share/tessdata/eng.traineddata` on Apple Silicon). Set `ingestion.prose_pdf.tessdata_dir` or `EE_WIKI_TESSDATA_DIR` if auto-detect fails. Install `chi_sim` / `osd` language packs for Chinese scans. |
| Schematic PDF not ingested | File must be under `.../sch/` |
| PDF ingest slow / OOM | Qwen3-VL-8B is heavy; ensure `EE_WIKI_MODELS_DIR` points to local weights. Watch INFO logs for `page N/M` and 30s heartbeats during inference. On Apple Silicon, device may show `mps`; otherwise `cpu` (very slow). |
| File always re-ingested | Sidecar missing or `source_mtime`/`source_size` absent (old run) |
| Processed not deleted after raw removed | Run full `python scripts/ingest.py` or directory scope, not single-file mode |
| Deleted docs still appear in query results | Run `python scripts/index.py` after ingest cleanup |
| Word `.doc` ingest fails | Install LibreOffice; verify `soffice --version`. Set `EE_WIKI_LIBREOFFICE_PATH` if needed. |
| Word `.docx` ingest fails | Run `pip install -e ".[dev,ml]"` for the `mammoth` dependency. |
| Path layout error | Path must match `{product}/{project}/{build}/{type}/file` (or reserved `global` / `common` forms) — see README Raw Data Layout |
| Legacy two-level paths | Run `scripts/migrate_raw_layout.py` then rebuild processed/indexes/graph — [ADR 0011 migration](#adr-0011-layout-migration) |

## Related docs

- [README — Raw Data Layout](../../README.md#raw-data-layout)
- [README — Metadata Standard](../../README.md#metadata-standard)
- [mcp.md](mcp.md) — component lookup, MCP tools, HTTP ingest
- [data-flow.md](../architecture/data-flow.md) — pipeline overview
