"""Pydantic request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitationModel(BaseModel):
    """Citation payload returned with generated answers."""

    source_file: str
    chunk_id: str
    page: int = 0
    excerpt: str = ""
    url: str = ""
    images: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    """Explicit RAG query request."""

    query: str
    project: str | None = None
    build: str | None = None
    document_type: str | None = None
    top_k: int | None = None
    task: str | None = None


class QueryResponse(BaseModel):
    """Explicit RAG query response."""

    answer: str
    citations: list[CitationModel]
    insufficient_context: bool = False


class ComponentHitModel(BaseModel):
    """One component lookup hit."""

    key: str
    kind: str
    chunk_id: str
    project: str
    build: str
    document_type: str
    source_file: str
    page: int = 0
    title: str
    excerpt: str = ""


class ComponentSearchResponse(BaseModel):
    """Component lookup response."""

    query: str
    hits: list[ComponentHitModel] = Field(default_factory=list)


class IngestRequest(BaseModel):
    """Admin request to trigger document ingest and optional index build."""

    path: str | None = Field(
        default=None,
        description="Optional file or directory under data/raw/ (relative or data/raw/...)",
    )
    paths: list[str] | None = Field(
        default=None,
        description="Optional list of paths under data/raw/; mutually exclusive with path",
    )
    project: str | None = Field(
        default=None,
        description="When path/paths omitted, scope ingest to data/raw/{project}/...",
    )
    build: str | None = Field(
        default=None,
        description="With project, scope to data/raw/{project}/{build}/",
    )
    force: bool = Field(
        default=False,
        description="Re-ingest and rebuild even when source fingerprints match",
    )
    ingest_only: bool = Field(
        default=False,
        description="Run ingest only; skip index build",
    )
    index_only: bool = Field(
        default=False,
        description="Run index build only; skip ingest",
    )


class IngestIssueModel(BaseModel):
    """One ingest failure or deferred-file warning."""

    path: str
    message: str


class IngestResponse(BaseModel):
    """Outcome of an ingest and optional index build run."""

    ingested: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0
    warnings: int = 0
    ingested_files: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)
    failed_files: list[IngestIssueModel] = Field(default_factory=list)
    warning_files: list[IngestIssueModel] = Field(default_factory=list)
    indexed_documents: int | None = None
    skipped_documents: int | None = None
    removed_documents: int | None = None
    chunk_count: int | None = None


class ChatMessage(BaseModel):
    """OpenAI-compatible chat message."""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with EE-Wiki filters."""

    model: str = "ee-wiki"
    messages: list[ChatMessage]
    stream: bool = False
    project: str | None = None
    build: str | None = None
    document_type: str | None = None
    top_k: int | None = None
    task: str | None = None


class ChatChoiceMessage(BaseModel):
    """Assistant message in an OpenAI-compatible response."""

    role: str = "assistant"
    content: str


class ChatChoice(BaseModel):
    """Single completion choice."""

    index: int = 0
    message: ChatChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    citations: list[CitationModel] = Field(default_factory=list)
    sources: list[dict[str, object]] = Field(default_factory=list)
    insufficient_context: bool = False
