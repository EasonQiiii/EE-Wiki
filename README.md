# EE-Wiki — Electronic Engineering Wiki

> AI-Native Electronic Engineering Knowledge Platform  
> Enterprise-grade Offline Engineering Wiki for Hardware Engineers

**Status:** V3 — offline hybrid RAG + knowledge graph (cases, power tree, rules, graph query API/MCP); see [Long-term Roadmap](#long-term-roadmap)

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | Rules and boundaries for AI coding assistants |
| [docs/usage/local-setup.md](docs/usage/local-setup.md) | **Local machine setup** (models, env, smoke test) |
| [docs/usage/ingest.md](docs/usage/ingest.md) | **How to run `scripts/ingest.py`** (raw → processed) |
| [docs/usage/knowledge-authoring.md](docs/usage/knowledge-authoring.md) | **How to write & place documents** (authoring spec for humans + AI) |
| [docs/usage/index.md](docs/usage/index.md) | **How to run `scripts/index.py`** (processed → indexes) |
| [docs/usage/query.md](docs/usage/query.md) | **CLI retrieval and RAG** (`query.py`, `ask.py`) |
| [docs/usage/mcp.md](docs/usage/mcp.md) | **V2 tools** — component lookup, MCP, HTTP ingest API |
| [docs/usage/eval.md](docs/usage/eval.md) | **RAG regression eval** (`eval_rag.py`, golden QA) |
| [docs/usage/open-webui.md](docs/usage/open-webui.md) | **Open WebUI** — chat connection, citations, MCP/tools wiring |
| [docs/architecture/repository-structure.md](docs/architecture/repository-structure.md) | Canonical directory layout and module boundaries |
| [docs/architecture/data-flow.md](docs/architecture/data-flow.md) | Ingestion and query pipelines |
| [docs/architecture/api-overview.md](docs/architecture/api-overview.md) | REST surface for Open WebUI |

---

# Vision

EE-Wiki is **not another RAG demo**.

It is designed to become an **AI-native Electronic Engineering Wiki**, providing a unified knowledge platform for hardware engineers, FA engineers, PCB designers, system architects and manufacturing engineers.

The long-term goal is to become an engineering operating system capable of understanding engineering documents, reasoning over schematic relationships, retrieving enterprise knowledge and collaborating with modern AI assistants such as Open WebUI.

Instead of simply searching documents, EE-Wiki should gradually evolve into an Engineering Knowledge Platform.

---



# Project Goals

The system should eventually support:

- Hardware Wiki
- Failure Analysis (FA)
- Hardware Debug
- Circuit Design Review
- Datasheet QA
- Schematic Analysis
- PCB Knowledge
- Manufacturing SOP
- Engineering FAQ
- Engineering Best Practice
- Debug Case Database
- Component Database
- Knowledge Graph
- Multi-Agent Collaboration

The project should never be limited to "FA Assistant".

It should become the company's engineering knowledge brain.

---



# Design Philosophy

The project follows several core principles.

## AI First

Everything is designed primarily for AI agents rather than human developers.

Documentation, APIs, metadata and project structure should all be optimized for AI coding assistants including:

- Codex
- Claude Code
- Cursor
- Gemini CLI
- OpenAI Agents
- MCP Clients

Humans should only define architecture.

AI should implement details.

---



## Offline First

The system must work completely offline.

No cloud dependency.

All models are local.

All documents remain inside enterprise infrastructure.

---



## Knowledge First

Large Language Models are **not** the knowledge source.

Knowledge comes from:

- Schematics
- Datasheets
- User Guides
- SOP
- Markdown
- Engineering Notes
- Debug Reports
- FA Reports
- PCB Documents
- Internal Wiki

The LLM is only responsible for reasoning and natural language generation.

---



## Modular Architecture

Every module has exactly one responsibility.

Parser should never retrieve.

Retriever should never generate.

Generator should never parse documents.

Knowledge should never depend on UI.

Everything should be replaceable.

---



# Overall Architecture

```
                     Open WebUI
                           │
                     OpenAI API
                           │
                  Engineering Wiki API
                           │
          ┌────────────────────────────────┐
          │                                │
          │        Wiki Engine             │
          │                                │
          └────────────────────────────────┘
                 │      │       │
                 │      │       │
         Retrieval  Knowledge  Tool Calling
                     Graph
                 │
          Engineering Database
```

Open WebUI is only the frontend.

EE-Wiki is the backend.

---



# Core Modules

The system consists of several independent modules.

## Document Ingestion

Responsible for:

- PDF
- Word
- PowerPoint
- Excel
- Markdown
- Images
- OCR

Output:

Standard Markdown + Metadata

---



## Knowledge Base

Stores

- cleaned documents
- metadata
- chunks
- embeddings
- indexes

Knowledge is the core asset.

Everything else can be regenerated.

---



## Hybrid Retrieval

Retrieval pipeline:

Metadata Filter

↓

Embedding Search

↓

BM25 Search

↓

Merge

↓

Reranker

↓

Top Context

This architecture allows both semantic retrieval and exact component lookup.

---



## Generator

The generator only receives:

Question

- 

Retrieved Context

It never directly accesses the database.

Prompt templates are separated by task.

Examples:

- Wiki
- Debug
- Design Review
- FA
- Compare
- Explain

---



## Knowledge Graph

Future versions should build engineering relationships.

Example:

```
VBAT
    │
    ▼
U0902
    │
    ▼
PMIC
    │
    ▼
Battery
```

This enables graph reasoning beyond traditional RAG.

---



# Supported Knowledge Types

The system should support multiple engineering document types.

```
Schematics

Datasheets

Application Notes

User Guides

SOP

Engineering Notes

Markdown

Debug Cases

Failure Analysis

PCB Documents

Manufacturing Documents

Test Reports

BOM

Firmware Documentation

FAQ
```

Every document should eventually share the same metadata schema.

---

# Raw Data Layout

Raw documents live under `data/raw/` (gitignored). Paths encode metadata — no manual tagging required for project, build, or document type.

## Directory Convention

```
data/raw/
├── global/                         # enterprise-wide shared (all projects)
│   ├── note/ sch/ sop/ datasheet/ fa/
├── {project}/                      # e.g. logan, elias, ruby
│   ├── common/                     # shared across all builds in this project
│   │   └── note/ sch/ sop/ fa/
│   └── {build}/                    # e.g. p1, p2
│       └── note/ sch/ sop/ fa/
└── ...
```

| Path segment | Meaning | What to store |
|--------------|---------|---------------|
| `global` | Enterprise-wide library (`project=global`, `build=global`) | Knowledge shared by **all projects**: generic tool usage, industry practices, common component datasheets, enterprise FA methods |
| `{project}` | A product line or program (e.g. `logan`) | — |
| `common` | Project-wide shared (`build=common`) | **This project's** cross-build knowledge: product architecture, naming rules, shared IP, project-level bring-up — not board-specific wiring |
| `{build}` | A specific hardware revision (e.g. `p1`, `p2`) | **Build truth**: schematics, build SOPs, debug notes for that revision |
| `note` / `sch` / `sop` / `datasheet` / `fa` | Document category folder | — |

Example:

```
data/raw/logan/p1/sch/power-tree.pdf
```

Supported raw formats (V1 priority): PDF, Markdown, TXT, Excel, Word. On macOS, Keynote (`.key`) and Numbers (`.numbers`) are ingested via AppleScript export — see [ADR 0004](docs/adr/0004-iwork-macos-export.md) and `ingestion.iwork` in `config/default.yaml`.

## Processed Mirror

After ingestion, `data/processed/` **mirrors the same path tree** as `data/raw/`:

```
data/raw/logan/p1/sch/power-tree.pdf
    →  data/processed/logan/p1/sch/power-tree.md   (+ sidecar metadata JSON)
```

Indexes under `data/indexes/` are flat or sharded by implementation; they reference metadata, not the folder tree.

## Path → Metadata

Ingestion derives metadata from the path relative to `data/raw/`:

| Path | `project` | `build` | `document_type` |
|------|-----------|---------|-----------------|
| `global/datasheet/tps62840.pdf` | `global` | `global` | `datasheet` |
| `logan/common/sop/bringup.md` | `logan` | `common` | `sop` |
| `logan/p1/sch/main.pdf` | `logan` | `p1` | `schematic` |
| `logan/p1/note/debug-log.txt` | `logan` | `p1` | `engineering_note` |

Folder → `document_type` mapping:

| Folder | `document_type` |
|--------|-----------------|
| `note` | `engineering_note` |
| `sch` | `schematic` |
| `sop` | `sop` |
| `datasheet` | `datasheet` |
| `fa` | `failure_analysis` |

New folders can be added in `config/default.yaml` → `data_layout.document_type_folders` without code changes.

---

# Metadata Standard

Every document should include standardized metadata.

Example (schematic — `sch/` folder; V2 adds optional per-page sidecar `pages`):

```json
{
  "project": "logan",
  "build": "p1",
  "document_type": "schematic",
  "page": 0,
  "title": "power-tree",
  "major_components": ["U101", "U102"],
  "nets": ["VBAT", "GND"],
  "interfaces": ["RMII"],
  "pages": [
    {"page": 1, "major_components": ["U101"], "nets": ["VBAT"], "interfaces": ["RMII"]},
    {"page": 2, "major_components": ["U102"], "nets": ["GND"], "interfaces": []}
  ],
  "keywords": [],
  "version": "",
  "source_file": "data/raw/logan/p1/sch/power-tree.pdf",
  "target_file": "data/processed/logan/p1/sch/power-tree.md"
}
```

Example (datasheet — `datasheet/` folder; V2 structured fields):

```json
{
  "project": "global",
  "build": "global",
  "document_type": "datasheet",
  "title": "STM32F407ZGT6",
  "supply_voltage": ["3.3V", "2.0V-3.6V"],
  "pin_count": 144,
  "package": "LQFP144",
  "interfaces": ["I2C", "SPI"],
  "keywords": ["STM32F407VGT6", "168MHZ"],
  "source_file": "data/raw/global/datasheet/STM32F407ZGT6.pdf",
  "target_file": "data/processed/global/datasheet/STM32F407ZGT6.md"
}
```

Example (failure analysis — `fa/` folder):

```json
{
  "project": "logan",
  "build": "p1",
  "document_type": "failure_analysis",
  "title": "RMA-2024-001",
  "keywords": ["ESD", "RMA:RMA-2024-001", "LOT:B2024-117"],
  "source_file": "data/raw/logan/p1/fa/rma-report.pdf",
  "target_file": "data/processed/logan/p1/fa/rma-report.md"
}
```

Example (engineering note — `note/` folder; no schematic fields):

```json
{
  "project": "logan",
  "build": "p1",
  "document_type": "engineering_note",
  "title": "iPadManual",
  "source_file": "data/raw/logan/p1/note/iPadManual.md",
  "target_file": "data/processed/logan/p1/note/iPadManual.md"
}
```

- **`source_file`** — original raw asset (citation / re-ingest)
- **`target_file`** — normalized content path used for chunking and retrieval
- **`major_components` / `nets` / `interfaces`** — schematic documents (`sch/`); at index time per-page values from `pages` are attached to each chunk
- **`supply_voltage` / `pin_count` / `package`** — datasheet documents (`datasheet/`), extracted during VLM ingest
- **`keywords`** — all document types; engineering terms, part numbers; FA reports also get failure-mode and traceability tokens (`RMA:`, `LOT:`, …)

Metadata is the foundation of enterprise retrieval.

---

# Retrieval Scope

When querying a specific project and build, retrieval **inherits upward** through shared libraries:

```
Query: project=logan, build=p1

Search scope (in priority order):
  1. logan / p1          ← build-specific
  2. logan / common      ← project-wide shared
  3. global / global     ← enterprise-wide shared
```

Rules:

- **Cascade retrieval** (default: `retrieval.scope_cascade: true`): search **build tier first**; expand to `common` only when the top build rerank score is below `scope_sufficient_rerank`; expand to `global` only when both build and common are insufficient. Product-only queries (`inherit`) cascade across all revision builds → `common` → `global` the same way.
- **Mixed quotas** (defaults in `config/default.yaml`): build tier fills up to `scope_quota_build` slots; `common` and `global` supplement remaining slots up to their quotas — they do not replace build evidence when build tier is sufficient.
- Build-specific documents rank highest; `common` and `global` provide fallback context.
- **`global/`** — enterprise or industry-wide background (tools, generic datasheets); answers must label it **global**, not as a specific board's fact.
- **`{project}/common/`** — that project's shared knowledge across builds; label as **project common**; does not override build-to-build differences.
- **`{project}/{build}/`** — authoritative board-level truth; engineering conclusions default here.
- Querying `project=logan, build=common` searches `logan/common` + `global` only.
- Querying `project=global` searches the enterprise library only.
- Scope inheritance is on by default (`config/default.yaml` → `retrieval.scope_inheritance`).

This ensures a question about `logan/p1` still finds datasheets in `global/datasheet/` and SOPs in `logan/common/sop/`.

### Answer presentation

Generated answers **must distinguish** `project` / `build` and knowledge layer:

- State which scope each conclusion applies to (e.g. `logan / p1`, `logan / common`, `global`).
- When context spans multiple scopes, structure the answer by scope; do not merge conflicting build-specific details.
- If the user did not specify `project` / `build`, list findings per scope and recommend specifying scope for a definitive build-level answer.
- Retrieval ranking (build > common > global) does not remove the need to label sources in the answer.

Implementation: tier cascade in `retrieval/scope_cascade.py` and `retrieval/hybrid/engine.py`; context block headers in `generation/context.py`; shared rules in `prompts/_shared/scope_rules.md`.

---

# Engineering Knowledge Hierarchy

Knowledge should be organized into multiple layers.

```
Enterprise

    ↓

Project

    ↓

Build

    ↓

Subsystem

    ↓

Circuit

    ↓

Component

    ↓

Pin

    ↓

Net
```

Every retrieval should understand these relationships.

---



# Open WebUI Integration

EE-Wiki is designed as a backend service.

Open WebUI is responsible for:

- Chat Interface
- Conversation Memory
- User Authentication
- Model Management
- Tool Calling
- MCP

EE-Wiki is responsible for:

- Knowledge
- Retrieval
- Engineering Reasoning
- Graph Query
- Component Search
- Engineering APIs

The two systems communicate through standard REST APIs (and later MCP).

---



# Future MCP Integration

The architecture should be fully compatible with MCP.

Future tools may include:

- search_component *(shipped)*
- search_datasheet *(shipped)*
- query_schematic *(shipped)*
- query_power_tree *(shipped)*
- search_debug_case *(shipped)*
- graph_query — neighbors / path / filter / open node *(shipped as `graph_*` + `open_graph_node` tools)*
- list_rules / evaluate_rules *(shipped)*
- bom_lookup
- engineering_search *(shipped)*

LLMs should call tools rather than relying only on prompts.

---



# Development Principles

Every module must have a single responsibility.

Every interface should be replaceable.

Every parser should output the same document format.

Every document should follow the same metadata schema.

Every retrieval should support metadata filtering.

Every prompt should be independent.

No business logic should be duplicated.

No hardcoded project-specific code.

No project-specific prompts.

No project-specific parser.

Everything should be reusable.

---



# Coding Standards

Prefer readability over cleverness.

Prefer explicit code over implicit behavior.

Prefer composition over inheritance.

Prefer interfaces over implementations.

Prefer configuration over hardcoding.

Prefer data-driven architecture.

Every public function must include:

- type hints
- docstring
- logging
- error handling

---



# Long-term Roadmap

Version 1

- Offline Hybrid RAG
- Markdown Knowledge Base
- Open WebUI Integration

Version 2

- Engineering Metadata (keywords, FA tokens, datasheet structured fields)
- Component Database (`components.json`, retrieval boost, HTTP + MCP lookup)
- Datasheet VLM Parser (page-classified extraction; OCR quality-gate fallback)
- Chunk-level schematic metadata (`pages` sidecar)
- Index inventory (`GET /v1/projects`, chat + MCP)
- MCP read-only tools + `POST /v1/ingest` (sync/async, optional API key)
- Better Retrieval (metadata boost, component boost, scope cascade, Figure/Table ranking)

Version 3 (current)

- Knowledge Graph (JSONL store, neighbors / path / scope filter; HTTP + MCP)
- Engineering Rules (YAML pack, evaluate API/MCP/CLI)
- Debug Case Database (`cases.json` + Case graph links)
- Power Tree Analysis (heuristic rails / supplies)
- Graph-aware prompts + optional `retrieval.graph_enrichment`

Version 4

- Multi-Agent System

Agents:

- Hardware Engineer
- FA Engineer
- PCB Engineer
- Manufacturing Engineer
- SI Engineer
- Power Engineer

Version 5

Enterprise Engineering Operating System

---



# What This Project Is NOT

This is NOT:

- another chatbot
- another RAG demo
- another PDF QA project
- another OpenAI wrapper

This project aims to become an AI-native engineering knowledge platform for modern hardware organizations.

---



# Final Mission

> Build the engineering brain that every hardware engineer wishes existed.

Instead of asking:

"Where is the document?"

Engineers should simply ask:

"Why is VBAT missing on U0902?"

And the system should understand:

- the schematic
- the datasheet
- the debug history
- the FA cases
- the engineering knowledge
- the enterprise best practices

before producing an answer.

That is the ultimate vision of EE-Wiki.