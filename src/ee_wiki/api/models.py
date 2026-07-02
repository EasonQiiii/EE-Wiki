"""Pydantic request and response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitationModel(BaseModel):
    """Citation payload returned with generated answers."""

    source_file: str
    chunk_id: str
    page: int = 0
    excerpt: str = ""


class QueryRequest(BaseModel):
    """Explicit RAG query request."""

    query: str
    project: str | None = None
    build: str | None = None
    document_type: str | None = None
    top_k: int | None = None


class QueryResponse(BaseModel):
    """Explicit RAG query response."""

    answer: str
    citations: list[CitationModel]
    insufficient_context: bool = False


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
    insufficient_context: bool = False
