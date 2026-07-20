"""Pydantic request and response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    product: str | None = None
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
    product: str = ""
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


class CaseHitModel(BaseModel):
    """One debug-case lookup hit."""

    case_id: str
    product: str = ""
    project: str
    build: str
    title: str
    source_file: str
    document_type: str = "failure_analysis"
    symptom: str = ""
    suspected_nets: list[str] = Field(default_factory=list)
    suspected_parts: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    root_cause: str = ""
    case_citations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class CaseSearchResponse(BaseModel):
    """Debug-case lookup response."""

    query: str
    hits: list[CaseHitModel] = Field(default_factory=list)


class PowerTreeResponse(BaseModel):
    """Power-tree query response (V3 P3 heuristic rails / supplies)."""

    query: str = ""
    direction: str = "tree"
    product: str | None = None
    project: str | None = None
    build: str | None = None
    resolved_id: str | None = None
    hits: list[dict] = Field(default_factory=list)
    feeds: list[dict] = Field(default_factory=list)
    tree: str | None = None
    flags: list[dict] = Field(default_factory=list)
    limitations: str = ""


class RuleCitationModel(BaseModel):
    """Citation attached to a rule evaluation result."""

    kind: str
    ref: str
    product: str = ""
    project: str = ""
    build: str = ""
    excerpt: str = ""


class RuleDefinitionModel(BaseModel):
    """One engineering rule from the YAML pack."""

    id: str
    name: str
    description: str = ""
    check_type: str
    severity: str = "warning"
    enabled: bool = True
    params: dict = Field(default_factory=dict)
    source_path: str = ""


class RuleResultModel(BaseModel):
    """Outcome of evaluating one engineering rule."""

    rule_id: str
    name: str = ""
    status: str
    severity: str = "warning"
    message: str = ""
    citations: list[RuleCitationModel] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class RuleListResponse(BaseModel):
    """List of configured engineering rules."""

    pack_dir: str = ""
    rules: list[RuleDefinitionModel] = Field(default_factory=list)


class RuleEvaluateResponse(BaseModel):
    """Engineering rules evaluation response (V3 P4)."""

    product: str | None = None
    project: str | None = None
    build: str | None = None
    pack_dir: str = ""
    counts: dict = Field(default_factory=dict)
    results: list[RuleResultModel] = Field(default_factory=list)
    limitations: str = ""


class GraphNeighborsResponse(BaseModel):
    """Neighbor query response (V3 P5)."""

    node_id: str = ""
    resolved_id: str | None = None
    product: str | None = None
    project: str | None = None
    build: str | None = None
    max_hops: int = 1
    edge_types: list[str] | None = None
    neighbors: list[dict] = Field(default_factory=list)


class GraphPathResponse(BaseModel):
    """Shortest-path query response (V3 P5)."""

    source: str = ""
    target: str = ""
    resolved_source: str | None = None
    resolved_target: str | None = None
    product: str | None = None
    project: str | None = None
    build: str | None = None
    max_depth: int = 8
    edge_types: list[str] | None = None
    path: list[dict] | None = None
    found: bool = False


class GraphNodesResponse(BaseModel):
    """Scope-filtered node listing (V3 P5)."""

    product: str | None = None
    project: str | None = None
    build: str | None = None
    node_types: list[str] | None = None
    nodes: list[dict] = Field(default_factory=list)
    count: int = 0


class GraphNodeResponse(BaseModel):
    """Single node open/lookup response (V3 P5)."""

    query: str = ""
    resolved_id: str | None = None
    product: str | None = None
    project: str | None = None
    build: str | None = None
    node: dict | None = None


class ProjectInventoryEntryModel(BaseModel):
    """One indexed project path with builds and chunk count."""

    product: str = ""
    project: str
    builds: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    is_enterprise: bool = False


class ProjectInventoryResponse(BaseModel):
    """Index project/build inventory."""

    chunk_count: int = 0
    product_count: int = 0
    enterprise_project: str = "global"
    project_shared_build: str = "common"
    projects: list[ProjectInventoryEntryModel] = Field(default_factory=list)


class IngestRequest(BaseModel):
    """Admin request to trigger document ingest and optional index build."""

    model_config = ConfigDict(populate_by_name=True)

    path: str | None = Field(
        default=None,
        description="Optional file or directory under data/raw/ (relative or data/raw/...)",
    )
    paths: list[str] | None = Field(
        default=None,
        description="Optional list of paths under data/raw/; mutually exclusive with path",
    )
    product: str | None = Field(
        default=None,
        description="When path/paths omitted, scope ingest to data/raw/{product}/...",
    )
    project: str | None = Field(
        default=None,
        description="With product, scope to data/raw/{product}/{project}/...",
    )
    build: str | None = Field(
        default=None,
        description="With product and project, scope to data/raw/{product}/{project}/{build}/",
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
    async_mode: bool = Field(
        default=False,
        alias="async",
        description=(
            "When true, accept the job immediately (202) and run ingest in the "
            "background; poll GET /v1/ingest/jobs/{job_id} for status"
        ),
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


IngestJobStatusLiteral = Literal["queued", "running", "succeeded", "failed"]


class IngestJobAccepted(BaseModel):
    """202 Accepted payload when ``async: true`` starts a background ingest job."""

    job_id: str
    status: IngestJobStatusLiteral = "queued"
    status_url: str
    message: str = "Ingest job accepted; poll status_url for progress"


class IngestJobStatusResponse(BaseModel):
    """Poll response for ``GET /v1/ingest/jobs/{job_id}``."""

    job_id: str
    status: IngestJobStatusLiteral
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: IngestResponse | None = None


class ConnectivityTraceResponse(BaseModel):
    """Schematic connectivity sidecar query response (ADR 0009)."""

    query: str = ""
    kind: str = ""
    found: bool = False
    authoritative: bool = False
    authority: str = ""
    product: str | None = None
    project: str | None = None
    build: str | None = None
    resolved_net: str | None = None
    resolved_refdes: str | None = None
    match: str | None = None
    page: int | None = None
    pins: list[dict] = Field(default_factory=list)
    pin_count: int = 0
    connectors: list[dict] = Field(default_factory=list)
    modules: list[dict] = Field(default_factory=list)
    advisory_pins: list[dict] = Field(default_factory=list)
    advisory_connectors: list[dict] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
    limitations: str = ""
    note: str | None = None
    error: str | None = None


class ChatMessage(BaseModel):
    """OpenAI-compatible chat message."""

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with EE-Wiki filters."""

    model: str = "ee-wiki"
    messages: list[ChatMessage]
    stream: bool = False
    product: str | None = None
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
