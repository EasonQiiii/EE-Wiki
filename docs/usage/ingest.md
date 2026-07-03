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

Schematic PDF parsing requires ML extras (`ee-wiki[ml]`) and models configured in `config/default.yaml`:

- `layoutlmv3-base` — LayoutLM figure crop for `sch/` PDFs (stage 1)
- `Qwen3-VL-4B-Instruct` — vision reconstruction for `sch/` PDFs (stage 2)
- Markdown / TXT need no models

## Where to put raw files

Place documents under `data/raw/` using this layout (see [Raw Data Layout](../../README.md#raw-data-layout) in README):

```
data/raw/
├── global/                    # enterprise-wide shared
├── {project}/                 # e.g. logan
│   ├── common/                # shared across builds in this project
│   └── {build}/               # e.g. p1
│       ├── note/              # engineering notes (.md, .txt)
│       ├── sch/               # schematics (.pdf)
│       └── sop/               # SOPs
```

### Where to put a document

| Put it under | When |
|--------------|------|
| `global/{type}/` | Shared by **all projects** — generic tool guides, industry practices, common component datasheets |
| `{project}/common/{type}/` | Shared by **all builds in that project** — product architecture, project naming, cross-build SOPs |
| `{project}/{build}/{type}/` | Specific to **one hardware revision** — schematics, build debug notes, that build's procedures |

See [README — Retrieval Scope](../../README.md#retrieval-scope) for how retrieval and answers treat each layer.

For **how to write** Markdown (glossaries, lifecycle docs, templates for AI reformatting), see [knowledge-authoring.md](knowledge-authoring.md).

Supported formats (V1):

| Folder | Formats |
|--------|---------|
| `note/`, `sop/`, `datasheet/`, etc. | `.md`, `.markdown`, `.txt`, `.pdf` (text + OCR), `.xlsx`, `.doc`, `.docx` |
| `sch/` | `.pdf` (schematic vision pipeline) |

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
python scripts/ingest.py data/raw/logan/p1/
```

- Scope: all ingestible files under that directory
- Cleanup: only within the matching `data/processed/logan/p1/` subtree

### Ingest a single file

```bash
python scripts/ingest.py data/raw/acme/p2/sch/board.pdf
python scripts/ingest.py data/raw/acme/p2/note/bringup.md
```

- Scope: that file only
- Cleanup: **disabled** (other processed files are not touched)

Use this when you want to re-run one document without scanning the full tree.

### Force re-ingest

```bash
python scripts/ingest.py --force
python scripts/ingest.py data/raw/logan/p1/note/ --force
```

Ignores `source_mtime` / `source_size` in existing sidecars and re-processes every file in scope.

### Verbose logging

```bash
python scripts/ingest.py -v
python scripts/ingest.py data/raw/logan/p1/sch/board.pdf --verbose
```

Sets EE-Wiki log level to DEBUG (useful for transformers load details). Schematic PDF ingest always logs page progress at INFO:

```
INFO  Ingesting: acme/p2/sch/board.pdf
INFO  Schematic PDF board.pdf: starting vision extraction for 5 page(s)
INFO  Schematic PDF board.pdf: page 1/5
INFO  Vision inference started: page 1 (image 4960x3508, 2.1 MB)
INFO  Vision inference page 1 still running (30s elapsed)
INFO  Vision inference finished: page 1 in 842.3s (1523 output tokens)
```

Long-running vision inference emits a heartbeat every 30 seconds so a silent terminal does not look hung.

## Incremental ingest

Each sidecar (`.meta.json`) stores a fingerprint of the raw file:

```json
{
  "source_file": "data/raw/acme/p2/note/bringup.md",
  "target_file": "data/processed/acme/p2/note/bringup.md",
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
| `python scripts/ingest.py data/raw/logan/p1/` | `data/processed/logan/p1/` only |
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
data/raw/logan/p1/note/manual.pdf
    →  data/processed/logan/p1/note/manual.md
    →  data/processed/logan/p1/note/manual.md.meta.json

data/raw/logan/p1/sch/board.pdf
    →  data/processed/logan/p1/sch/board.md
    →  data/processed/logan/p1/sch/board.md.meta.json

data/raw/logan/p1/note/manual.md
    →  data/processed/logan/p1/note/manual.md
    →  data/processed/logan/p1/note/manual.md.meta.json
```

Prose PDFs (`note/`, `sop/`, `datasheet/`, …) emit per-page `## Page N` sections for chunking. Schematic PDFs use the **temp3 two-stage pipeline**:

1. **LayoutLMv3** — OCR text + figure region crop → `data/processed/.../sch/images/<pdf>_p<N>_crop_*.png`
2. **Qwen3-VL** — reconstruct Markdown from OCR text + crop image (system FA expert prompt)
3. **Fallback** — rule-based report if VLM fails

Output merges per-page reports under one `# 电子图纸分析报告：{title}` document. Metadata includes `major_components`, `nets`, and `interfaces`.

## CLI summary

```bash
# stderr summary after each run:
# Ingested: 1, skipped (unchanged): 2, removed (raw deleted): 1

# stdout lists paths for newly ingested files:
# /path/to/data/processed/logan/p1/note/new.md
# /path/to/data/processed/logan/p1/note/new.md.meta.json
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
| Path layout error | Path must match `{project}/{build}/{type}/file` — see README Raw Data Layout |

## Related docs

- [README — Raw Data Layout](../../README.md#raw-data-layout)
- [README — Metadata Standard](../../README.md#metadata-standard)
- [data-flow.md](../architecture/data-flow.md) — pipeline overview
