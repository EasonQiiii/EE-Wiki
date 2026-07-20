# 0011. Three-level scope hierarchy: product / project / build

Date: 2026-07-18
Status: accepted

## Context

EE-Wiki originally encoded document scope with two path levels plus an
enterprise library:

```
global/{type}/<file>                  → project=global, build=global
{project}/{build}/{type}/<file>       → build truth
{project}/common/{type}/<file>        → project-wide shared (build=common)
```

The metadata/filter model therefore carried only two scope axes (`project`,
`build`) and retrieval inherited upward as `build → project common → global`.

In practice a single **product line** (e.g. `iphone`) contains multiple
**projects/programs** (e.g. `logan`, `macon`), each with several **hardware
builds** (e.g. `p1`, `p2`). The old two-level model forced either the product
or the project to be dropped, collapsing distinct programs into one namespace
and preventing a "project common" tier that is shared across a program's
builds but not across the whole product.

## Decision

Adopt a canonical **three-level scope hierarchy** — `product` / `project` /
`build` — with two reserved words, `global` (enterprise top) and `common`
(shared tier). Canonical raw paths:

| Path | product | project | build |
|------|---------|---------|-------|
| `global/{type}/<file>` | `global` | `global` | `global` |
| `{product}/common/{type}/<file>` | `{product}` | `common` | `common` |
| `{product}/{project}/common/{type}/<file>` | `{product}` | `{project}` | `common` |
| `{product}/{project}/{build}/{type}/<file>` | `{product}` | `{project}` | `{build}` |

Rules:

- **Metadata and `MetadataFilter` require all three axes**: `product`,
  `project`, `build`.
- **Reserved words** `global` and `common` may not be used as ordinary
  product/project/build slugs. They are only valid in their reserved positions.
- **Inheritance order** (most specific first):
  `build truth → project common → product common → global`. Expansion returns
  `(product, project, build)` triples:
  1. `(product, project, build)`
  2. `(product, project, common)`
  3. `(product, common, common)`
  4. `(global, global, global)`
- **Strict cutover**: there is no legacy two-level fallback parser. Existing
  raw trees must be re-laid-out and re-ingested against the canonical paths.

The config keys `data_layout.enterprise_project` (`global`) and
`data_layout.project_shared_build` (`common`) are retained as the source of the
two reserved words; `DataLayoutConfig` exposes them as `global_segment` /
`common_segment` / `reserved_segments` for callers.

## Consequences

- `common/types.py`, `common/serialization.py`, `config/schema/metadata.schema.json`,
  and `ingestion/path_metadata.py` change in this foundation phase; the parser
  emits triples and rejects reserved names in ordinary segments.
- Because `Metadata` now requires `product`, every downstream `Metadata(...)`
  construction, `MetadataFilter` usage, and every caller of
  `expand_retrieval_scope(...)` (retrieval, graph, API, ingestion parsers, tools)
  must be updated in follow-up phases. These are intentional, tracked breakages
  — this ADR covers only the common types, serialization, schema, config, and
  path parser foundation.
- Retrieval ranking, scope catalog/cascade/resolve, graph build/query, and the
  HTTP/MCP scope surfaces will migrate to the triple model in subsequent phases.
- Persisted indexes and processed sidecars written before this change lack
  `product` and must be rebuilt.

### Cutover (legacy two-level → three-level)

Use `scripts/migrate_raw_layout.py` to move
`data/raw/{project}/...` → `data/raw/{product}/{project}/...` with an explicit
project→product map. Default is dry-run; `--apply` executes. The tool leaves
`data/raw/global/` alone, refuses reserved names / collisions, and does **not**
relocate processed, indexes, graph, or FA cache/exports (Radar-keyed).

Operator sequence after a successful apply:

1. Migrate raw (dry-run, then `--apply`)
2. Delete / recreate `data/processed/`, `data/indexes/`, and `data/graph/`
3. Ingest → index → `build_graph`

Details: [docs/usage/ingest.md](../usage/ingest.md#adr-0011-layout-migration).
