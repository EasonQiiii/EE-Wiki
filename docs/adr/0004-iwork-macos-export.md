# 0004. Apple iWork Ingest via macOS Export

Date: 2026-07-07
Status: accepted

## Context

V1 ingest supports PDF, Markdown, TXT, Excel, and Word. Enterprise teams often keep review decks in Keynote (`.key`) and BOM or parameter tables in Numbers (`.numbers`). These formats were previously deferred with a log message asking operators to export manually.

LibreOffice does not reliably open native iWork files. Apple’s own Keynote and Numbers applications produce the best export fidelity. EE-Wiki already uses a **conversion ingest** pattern for legacy `.doc` files (LibreOffice → PDF → `parse_prose_pdf`).

## Decision

On **macOS only**, ingest `.key` and `.numbers` by controlling Keynote and Numbers through **AppleScript** (`osascript`):

| Source | Export | Downstream parser |
|--------|--------|-------------------|
| `.key` | PDF via Keynote | `parse_prose_pdf` (metadata from original `.key`) |
| `.numbers` | `.xlsx` via Numbers | `parse_excel` (metadata from original `.numbers`) |

Implementation: [`src/ee_wiki/ingestion/parsers/iwork/`](../../src/ee_wiki/ingestion/parsers/iwork/).

### Configuration

`config/default.yaml` → `ingestion.iwork`:

- `enabled` — master switch (default `true` on Mac deployments)
- `keynote_export_timeout_seconds` / `numbers_export_timeout_seconds` — default 600
- `quit_apps_after_export` — default `false` for faster batch sync

### Platform and concurrency

- Non-macOS hosts: `.key` / `.numbers` are skipped with a warning (same as before when `enabled: false`).
- iWork export runs under a **process-wide lock** — Keynote/Numbers cannot safely export in parallel.
- Export is **not headless**: Keynote/Numbers may show windows; a GUI session and Automation permissions are required.

### Processed mirror

Exported PDF/xlsx files are temporary. Processed output is `.md` under `data/processed/`, mirroring the raw `.key` / `.numbers` path. Citations reference the original iWork source file.

## Consequences

### Positive

- Operators can drop `.key` / `.numbers` directly into `data/raw/` on Mac.
- Reuses existing prose PDF and Excel parsers; no duplicate text extraction logic.
- Offline; no cloud conversion APIs.

### Negative / limits

- macOS-only; Linux CI and servers must continue to skip or pre-export iWork files.
- Slower and less robust than native parsers; large decks may hit export timeouts.
- Requires Keynote and Numbers installed and Automation permission for the ingest process.
- First ADR-tier ingest path tied to GUI applications (similar operational burden to LibreOffice for `.doc`).

### Follow-ups

- Optional batch pre-export script for non-Mac build agents.
- Metrics on export duration to tune timeouts at 10GB-scale corpora.
