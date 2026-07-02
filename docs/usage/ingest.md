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

Supported formats (V1):

| Folder | Formats |
|--------|---------|
| `note/`, `sop/`, etc. | `.md`, `.markdown`, `.txt` |
| `sch/` | `.pdf` (schematic PDF only) |

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

## Output layout

```
data/raw/logan/p1/sch/board.pdf
    →  data/processed/logan/p1/sch/board.md
    →  data/processed/logan/p1/sch/board.md.meta.json

data/raw/logan/p1/note/manual.md
    →  data/processed/logan/p1/note/manual.md
    →  data/processed/logan/p1/note/manual.md.meta.json
```

Schematic PDFs use the **temp3 two-stage pipeline**:

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
| PDF not ingested | File must be under `.../sch/`; other PDF paths are rejected in V1 |
| PDF ingest slow / OOM | Qwen3-VL-8B is heavy; ensure `EE_WIKI_MODELS_DIR` points to local weights. Watch INFO logs for `page N/M` and 30s heartbeats during inference. On Apple Silicon, device may show `mps`; otherwise `cpu` (very slow). |
| File always re-ingested | Sidecar missing or `source_mtime`/`source_size` absent (old run) |
| Processed not deleted after raw removed | Run full `python scripts/ingest.py` or directory scope, not single-file mode |
| Path layout error | Path must match `{project}/{build}/{type}/file` — see README Raw Data Layout |

## Related docs

- [README — Raw Data Layout](../../README.md#raw-data-layout)
- [README — Metadata Standard](../../README.md#metadata-standard)
- [data-flow.md](../architecture/data-flow.md) — pipeline overview
