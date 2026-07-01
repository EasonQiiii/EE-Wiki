# Data Flow

High-level pipeline for EE-Wiki V1. Detailed contracts live in `src/ee_wiki/common/types.py` (when implemented).

## Ingestion (write path)

```
Raw file under data/raw/{project}/{build}/{type}/…
    → path parser (derive project, build, document_type)
    → ingestion/parsers/*
    → StandardDocument (Markdown + Metadata)
    → knowledge/store → data/processed/  (mirrors raw tree)
    → chunker
    → knowledge/indexer (embeddings + BM25)
    → indexes on disk under data/indexes/
```

## Query (read path)

```
User question (via Open WebUI → api/)
    → metadata filter (project, build, document_type)
    → scope expansion: build → + project/common → + global  (when scope_inheritance=true)
    → retrieval/ (embedding + BM25 + merge + rerank)
    → top chunks with Citations
    → generation/ (prompt template + local LLM)
    → answer with citations
```

## Rules

- Generators receive **question + retrieved chunks only** — no direct DB reads.
- Retrievers never call the LLM.
- Parsers never write indexes directly; they go through the knowledge layer.
