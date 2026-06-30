# EE-Wiki — Electronic Engineering Wiki

> AI-Native Electronic Engineering Knowledge Platform  
> Enterprise-grade Offline Engineering Wiki for Hardware Engineers

---

# Vision

BYDEE101 is **not another RAG demo**.

It is designed to become an **AI-native Electronic Engineering Wiki**, providing a unified knowledge platform for hardware engineers, FA engineers, PCB designers, system architects and manufacturing engineers.

The long-term goal is to become an engineering operating system capable of understanding engineering documents, reasoning over schematic relationships, retrieving enterprise knowledge and collaborating with modern AI assistants such as Open WebUI.

Instead of simply searching documents, BYDEE101 should gradually evolve into an Engineering Knowledge Platform.

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

BYDEE101 is the backend.

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

+

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

# Metadata Standard

Every document should include standardized metadata.

Example:

```json
{
  "project": "",
  "board": "",
  "document_type": "",
  "page": 0,
  "title": "",
  "major_components": [],
  "nets": [],
  "interfaces": [],
  "keywords": [],
  "version": "",
  "source_file": ""
}
```

Metadata is the foundation of enterprise retrieval.

---

# Engineering Knowledge Hierarchy

Knowledge should be organized into multiple layers.

```
Enterprise

    ↓

Project

    ↓

Board

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

BYDEE101 is designed as a backend service.

Open WebUI is responsible for:

- Chat Interface
- Conversation Memory
- User Authentication
- Model Management
- Tool Calling
- MCP

BYDEE101 is responsible for:

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

- search_component
- search_datasheet
- query_schematic
- query_power_tree
- search_debug_case
- graph_query
- bom_lookup
- engineering_search

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

- Engineering Metadata
- Component Database
- Datasheet Parser
- Better Retrieval

Version 3

- Knowledge Graph
- Engineering Rules
- Debug Case Database
- Power Tree Analysis

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

That is the ultimate vision of BYDEE101.