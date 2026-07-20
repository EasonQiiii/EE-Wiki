# Architecture Decision Records

Record non-trivial decisions here using this template:

```
docs/adr/NNNN-short-title.md
```

## Template

```markdown
# NNNN. Title

Date: YYYY-MM-DD
Status: proposed | accepted | deprecated

## Context

## Decision

## Consequences
```

## Index

- [0001-chunking-strategy.md](0001-chunking-strategy.md) — document chunking defaults for V1 retrieval
- [0002-v1-runtime-stack.md](0002-v1-runtime-stack.md) — on-disk index, sentence-transformers, MLX/Transformers LLM
- [0003-external-llm-openai-compatible.md](0003-external-llm-openai-compatible.md) — OpenAI-compatible HTTP LLM backend
- [0004-iwork-macos-export.md](0004-iwork-macos-export.md) — Keynote/Numbers ingest via macOS AppleScript export
- [0005-datasheet-figure-table-retrieval.md](0005-datasheet-figure-table-retrieval.md) — Figure/Table vs Page retrieval, negated modifier ranking, ingest label enrichment
- [0006-knowledge-graph-store.md](0006-knowledge-graph-store.md) — V3 offline JSONL graph bundle under `data/graph/`, module boundaries, scope inheritance
- [0007-schematic-connectivity-extraction.md](0007-schematic-connectivity-extraction.md) — CAD-first schematic module↔net ladder; PDF connector geometry fallback; OCR spatial last
- [0008-multi-agent-runtime.md](0008-multi-agent-runtime.md) — V4 supervisor + read-only ToolBus; config-driven roles; write bans (accepted)
- [0009-multi-source-schematic-map.md](0009-multi-source-schematic-map.md) — PDF + BoardView `.brd` + netlist complementary connectivity map; evidence merge; sidecar v2
- [0010-fa-session-external-integrations.md](0010-fa-session-external-integrations.md) — Radar-keyed FA session; Flames/Radar connectors; Keynote export + download (proposed)
- [0011-product-project-build-hierarchy.md](0011-product-project-build-hierarchy.md) — three-level scope (product/project/build); reserved `global`/`common`; triple inheritance; strict cutover (accepted)
- [0012-chat-pipeline-grounding.md](0012-chat-pipeline-grounding.md) — chat gates once; rules-first route; hybrid RAG + citations for agent turns (accepted)
