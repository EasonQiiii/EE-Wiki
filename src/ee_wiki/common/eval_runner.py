"""Run retrieval and RAG evaluation against the golden QA dataset."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from ee_wiki.common.config import AppConfig
from ee_wiki.common.eval_qa import EvalCase, EvalDataset, EvalFilters, load_qa_dataset
from ee_wiki.common.types import Citation, RagAnswer
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult

EvalMode = Literal["retrieval", "generation", "both"]

INSUFFICIENT_MARKERS = (
    "知识库中未找到",
    "知识库缺乏",
    "insufficient knowledge",
    "insufficient context",
    "无法回答",
    "未找到相关内容",
    "未找到相关",
)


class RetrievalEngine(Protocol):
    """Minimal retrieval interface used by the eval runner."""

    def retrieve(
        self,
        query: str,
        *,
        target_product: str | None = None,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
    ) -> RetrievalResult:
        """Run hybrid retrieval for a query."""
        ...


class RagAnswerEngine(Protocol):
    """Minimal end-to-end RAG interface used by the eval runner."""

    def answer(
        self,
        question: str,
        *,
        target_product: str | None = None,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
        task: str | None = None,
    ) -> RagAnswer:
        """Generate a grounded answer for a question."""
        ...


DEFAULT_FACT_RECALL_THRESHOLD = 0.6
DEFAULT_NEGATIVE_RERANK_CEILING = -2.0
DEFAULT_ANSWER_PREVIEW_CHARS = 240


@dataclass(frozen=True)
class QueryEvalResult:
    """Retrieval metrics for one query variant."""

    query: str
    source_hit: bool
    source_hit_rank: int | None
    facts_found: int
    facts_total: int
    fact_recall: float
    top_rerank_score: float | None
    matched_sources: tuple[str, ...]
    chunk_count: int
    forbidden_scope_hit: bool
    forbidden_text_hit: bool


@dataclass(frozen=True)
class GenerationQueryResult:
    """Generation metrics for one query variant."""

    query: str
    answer_preview: str
    insufficient_context: bool
    answer_facts_found: int
    answer_facts_total: int
    answer_fact_recall: float
    citation_hit: bool
    must_not_violated: bool
    refusal_detected: bool
    generation_pass: bool


@dataclass(frozen=True)
class CaseEvalResult:
    """Aggregated retrieval and optional generation metrics for one golden QA case."""

    case_id: str
    title: str
    category: str
    mandatory: bool
    query_results: tuple[QueryEvalResult, ...]
    source_pass: bool
    facts_pass: bool
    negative_pass: bool
    stability_pass: bool
    overall_pass: bool
    generation_results: tuple[GenerationQueryResult, ...] = ()
    generation_pass: bool = True
    answer_facts_pass: bool = True
    citation_pass: bool = True
    refusal_pass: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the case result for JSON reports.

        Returns:
            JSON-serializable mapping for this case.
        """
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "title": self.title,
            "category": self.category,
            "mandatory": self.mandatory,
            "source_pass": self.source_pass,
            "facts_pass": self.facts_pass,
            "negative_pass": self.negative_pass,
            "stability_pass": self.stability_pass,
            "generation_pass": self.generation_pass,
            "answer_facts_pass": self.answer_facts_pass,
            "citation_pass": self.citation_pass,
            "refusal_pass": self.refusal_pass,
            "overall_pass": self.overall_pass,
            "queries": [
                {
                    "query": item.query,
                    "source_hit": item.source_hit,
                    "source_hit_rank": item.source_hit_rank,
                    "facts_found": item.facts_found,
                    "facts_total": item.facts_total,
                    "fact_recall": round(item.fact_recall, 4),
                    "top_rerank_score": item.top_rerank_score,
                    "matched_sources": list(item.matched_sources),
                    "chunk_count": item.chunk_count,
                    "forbidden_scope_hit": item.forbidden_scope_hit,
                    "forbidden_text_hit": item.forbidden_text_hit,
                }
                for item in self.query_results
            ],
        }
        if self.generation_results:
            payload["generation"] = [
                {
                    "query": item.query,
                    "answer_preview": item.answer_preview,
                    "insufficient_context": item.insufficient_context,
                    "answer_facts_found": item.answer_facts_found,
                    "answer_facts_total": item.answer_facts_total,
                    "answer_fact_recall": round(item.answer_fact_recall, 4),
                    "citation_hit": item.citation_hit,
                    "must_not_violated": item.must_not_violated,
                    "refusal_detected": item.refusal_detected,
                    "generation_pass": item.generation_pass,
                }
                for item in self.generation_results
            ]
        return payload


@dataclass(frozen=True)
class EvalReport:
    """Full retrieval and optional generation evaluation run."""

    dataset_version: str
    corpus_built_at: str
    top_k: int
    fact_recall_threshold: float
    case_results: tuple[CaseEvalResult, ...]
    mode: EvalMode = "retrieval"

    @property
    def total_cases(self) -> int:
        """Number of evaluated cases."""
        return len(self.case_results)

    @property
    def passed_cases(self) -> int:
        """Number of cases that passed overall."""
        return sum(1 for case in self.case_results if case.overall_pass)

    @property
    def mandatory_cases(self) -> tuple[CaseEvalResult, ...]:
        """Mandatory subset of case results."""
        return tuple(case for case in self.case_results if case.mandatory)

    @property
    def mandatory_pass_rate(self) -> float:
        """Fraction of mandatory cases that passed."""
        mandatory = self.mandatory_cases
        if not mandatory:
            return 1.0
        passed = sum(1 for case in mandatory if case.overall_pass)
        return passed / len(mandatory)

    @property
    def negative_pass_rate(self) -> float:
        """Fraction of negative cases that passed."""
        negative = [case for case in self.case_results if case.category == "negative"]
        if not negative:
            return 1.0
        passed = sum(1 for case in negative if case.negative_pass)
        return passed / len(negative)

    @property
    def source_hit_rate(self) -> float:
        """Fraction of non-negative cases with a required source hit."""
        non_negative = [case for case in self.case_results if case.category != "negative"]
        if not non_negative:
            return 1.0
        hits = sum(1 for case in non_negative if any(q.source_hit for q in case.query_results))
        return hits / len(non_negative)

    @property
    def generation_pass_rate(self) -> float:
        """Fraction of cases that passed generation scoring."""
        if self.mode == "retrieval":
            return 1.0
        if not self.case_results:
            return 1.0
        passed = sum(1 for case in self.case_results if case.generation_pass)
        return passed / len(self.case_results)

    def meets_thresholds(
        self,
        *,
        mandatory_accuracy: float = 0.90,
        negative_refusal_rate: float = 1.0,
    ) -> bool:
        """Return whether the run meets configured pass thresholds.

        Args:
            mandatory_accuracy: Minimum mandatory pass rate.
            negative_refusal_rate: Minimum negative pass rate.

        Returns:
            True when both thresholds are satisfied.
        """
        return (
            self.mandatory_pass_rate >= mandatory_accuracy
            and self.negative_pass_rate >= negative_refusal_rate
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full report for JSON output.

        Returns:
            JSON-serializable evaluation report.
        """
        return {
            "dataset_version": self.dataset_version,
            "corpus_built_at": self.corpus_built_at,
            "mode": self.mode,
            "top_k": self.top_k,
            "fact_recall_threshold": self.fact_recall_threshold,
            "summary": {
                "total_cases": self.total_cases,
                "passed_cases": self.passed_cases,
                "mandatory_pass_rate": round(self.mandatory_pass_rate, 4),
                "negative_pass_rate": round(self.negative_pass_rate, 4),
                "source_hit_rate": round(self.source_hit_rate, 4),
                "generation_pass_rate": round(self.generation_pass_rate, 4),
                "meets_thresholds": self.meets_thresholds(),
            },
            "cases": [case.to_dict() for case in self.case_results],
        }


def build_eval_config(config: AppConfig) -> AppConfig:
    """Return config tuned for deterministic golden QA evaluation.

    Args:
        config: Base application configuration.

    Returns:
        Copy with rewrite, scope inference, and assistant fallback disabled.
    """
    generation = replace(
        config.generation,
        query_rewrite=False,
        task_classification=False,
        scope_inference=False,
        assistant_fallback=False,
    )
    return replace(config, generation=generation)


def _select_cases(
    dataset: EvalDataset,
    *,
    case_ids: set[str] | None = None,
    categories: set[str] | None = None,
    mandatory_only: bool = False,
) -> list[EvalCase]:
    selected = list(dataset.cases)
    if case_ids:
        selected = [case for case in selected if case.id in case_ids]
    if categories:
        selected = [case for case in selected if case.category in categories]
    if mandatory_only:
        selected = [case for case in selected if case.mandatory]
    return selected


def normalize_eval_path(path: str) -> str:
    """Normalize document paths for golden-source matching.

    Args:
        path: Raw or processed document path, absolute or relative.

    Returns:
        Normalized ``data/processed/...`` or ``data/raw/...`` style path.
    """
    normalized = path.replace("\\", "/")
    for marker in ("data/processed/", "data/raw/"):
        index = normalized.find(marker)
        if index >= 0:
            return normalized[index:]
    return normalized


def chunk_document_paths(chunk: HybridChunk) -> tuple[str, ...]:
    """Collect comparable document paths from a retrieved chunk.

    Args:
        chunk: Retrieved hybrid chunk.

    Returns:
        Normalized path labels for source matching.
    """
    paths: list[str] = []
    target_file = chunk.metadata.get("target_file")
    if target_file:
        paths.append(normalize_eval_path(str(target_file)))
    source_file = chunk.citation.get("source_file")
    if source_file:
        paths.append(normalize_eval_path(str(source_file)))
    return tuple(paths)


def source_matches_required(required: str, chunk: HybridChunk) -> bool:
    """Return whether a chunk belongs to a required golden source document.

    Args:
        required: Expected processed document path from the QA dataset.
        chunk: Retrieved chunk candidate.

    Returns:
        True when the chunk maps to the required source document.
    """
    required_norm = normalize_eval_path(required)
    required_path = Path(required_norm)
    required_parent = required_path.parent.name
    required_stem = required_path.stem

    for candidate in chunk_document_paths(chunk):
        if path_matches_required(required_norm, candidate, required_stem, required_parent):
            return True
    return False


def path_matches_required(
    required_norm: str,
    candidate: str,
    required_stem: str | None = None,
    required_parent: str | None = None,
) -> bool:
    """Return whether a document path matches a required golden source.

    Args:
        required_norm: Normalized required path.
        candidate: Candidate document path.
        required_stem: Optional precomputed required filename stem.
        required_parent: Optional precomputed required parent directory name.

    Returns:
        True when the candidate maps to the required source document.
    """
    required_path = Path(required_norm)
    stem = required_stem or required_path.stem
    parent = required_parent or required_path.parent.name
    candidate_norm = normalize_eval_path(candidate)
    candidate_path = Path(candidate_norm)
    if candidate_norm == required_norm:
        return True
    return candidate_path.stem == stem and candidate_path.parent.name == parent


def _find_source_hit(
    chunks: list[HybridChunk],
    required_sources: tuple[str, ...],
) -> tuple[bool, int | None, tuple[str, ...]]:
    if not required_sources:
        return False, None, ()

    matched: list[str] = []
    first_rank: int | None = None
    for rank, chunk in enumerate(chunks, start=1):
        for required in required_sources:
            if source_matches_required(required, chunk):
                matched.append(required)
                if first_rank is None:
                    first_rank = rank
    return bool(matched), first_rank, tuple(dict.fromkeys(matched))


def _normalize_fact_text(text: str) -> str:
    """Normalize text for loose fact matching (spacing, case)."""
    return "".join(text.casefold().split())


def _fact_in_text(fact: str, text: str) -> bool:
    """Return whether a fact appears in text after normalization."""
    normalized_fact = _normalize_fact_text(fact)
    if not normalized_fact:
        return False
    if normalized_fact in _normalize_fact_text(text):
        return True
    return fact.casefold() in text.casefold()


def _fact_recall(
    chunks: list[HybridChunk],
    expected_facts: tuple[str, ...],
) -> tuple[int, int, float]:
    if not expected_facts:
        return 0, 0, 1.0

    combined = "\n".join(chunk.content for chunk in chunks)
    found = sum(1 for fact in expected_facts if _fact_in_text(fact, combined))
    total = len(expected_facts)
    return found, total, found / total


def _negative_forbidden_scope(
    chunks: list[HybridChunk],
    forbidden_scope: EvalFilters | None,
) -> bool:
    if forbidden_scope is None:
        return False
    for chunk in chunks:
        product = chunk.metadata.get("product")
        project = chunk.metadata.get("project")
        build = chunk.metadata.get("build")
        if project != forbidden_scope.project or build != forbidden_scope.build:
            continue
        if forbidden_scope.product and product != forbidden_scope.product:
            continue
        return True
    return False


def _forbidden_source_hit(
    chunks: list[HybridChunk],
    forbidden_sources: tuple[str, ...],
) -> bool:
    if not forbidden_sources:
        return False
    for chunk in chunks:
        for forbidden in forbidden_sources:
            if source_matches_required(forbidden, chunk):
                return True
    return False


def _forbidden_text_hit(chunks: list[HybridChunk], must_not_contain: tuple[str, ...]) -> bool:
    if not must_not_contain:
        return False
    combined = "\n".join(chunk.content for chunk in chunks)
    return any(token in combined for token in must_not_contain)


def _text_fact_recall(text: str, expected_facts: tuple[str, ...]) -> tuple[int, int, float]:
    if not expected_facts:
        return 0, 0, 1.0
    lowered = text
    found = sum(1 for fact in expected_facts if _fact_in_text(fact, lowered))
    total = len(expected_facts)
    return found, total, found / total


def _answer_preview(answer: str, *, max_chars: int = DEFAULT_ANSWER_PREVIEW_CHARS) -> str:
    compact = " ".join(answer.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _is_refusal_answer(answer: str, insufficient_context: bool) -> bool:
    if insufficient_context:
        return True
    lowered = answer.casefold()
    return any(marker.casefold() in lowered for marker in INSUFFICIENT_MARKERS)


def _citation_paths(citation: Citation) -> tuple[str, ...]:
    paths = [normalize_eval_path(citation.source_file)]
    raw = citation.source_file.replace("\\", "/")
    if raw.startswith("data/raw/"):
        paths.append(normalize_eval_path(raw.replace("data/raw/", "data/processed/", 1)))
    return tuple(dict.fromkeys(path for path in paths if path))


def _citation_hit(citations: list[Citation], required_sources: tuple[str, ...]) -> bool:
    if not required_sources:
        return False
    for citation in citations:
        for candidate in _citation_paths(citation):
            for required in required_sources:
                required_norm = normalize_eval_path(required)
                required_path = Path(required_norm)
                if path_matches_required(
                    required_norm,
                    candidate,
                    required_path.stem,
                    required_path.parent.name,
                ):
                    return True
    return False


def _citation_forbidden_scope(
    citations: list[Citation],
    filters: EvalFilters | None,
) -> bool:
    if filters is None:
        return False
    if filters.product:
        marker = f"{filters.product}/{filters.project}/{filters.build}"
    else:
        marker = f"{filters.project}/{filters.build}"
    for citation in citations:
        for candidate in _citation_paths(citation):
            if marker in candidate:
                return True
    return False


def _must_not_violated_text(text: str, must_not_contain: tuple[str, ...]) -> bool:
    if not must_not_contain:
        return False
    return any(token in text for token in must_not_contain)


def evaluate_generation(
    answer: RagAnswer,
    *,
    query: str,
    case: EvalCase,
    fact_recall_threshold: float,
) -> GenerationQueryResult:
    """Score a generated answer for one query variant.

    Args:
        answer: Generated RAG answer.
        query: Query string that was executed.
        case: Golden QA case definition.
        fact_recall_threshold: Minimum acceptable answer fact recall.

    Returns:
        Per-query generation metrics.
    """
    answer_text = answer.answer
    facts_found, facts_total, answer_fact_recall = _text_fact_recall(
        answer_text,
        case.expected_facts,
    )
    citation_hit = _citation_hit(answer.citations, case.required_sources)
    must_not_violated = _must_not_violated_text(answer_text, case.must_not_contain)
    refusal_detected = _is_refusal_answer(answer_text, answer.insufficient_context)
    forbidden_scope = _citation_forbidden_scope(answer.citations, case.filters)

    if case.category == "negative":
        generation_pass = (
            refusal_detected
            and not must_not_violated
            and not forbidden_scope
        )
    else:
        answer_facts_pass = (
            answer_fact_recall >= fact_recall_threshold if facts_total > 0 else True
        )
        citation_ok = citation_hit if case.required_sources else True
        generation_pass = (
            not refusal_detected
            and answer_facts_pass
            and citation_ok
            and not must_not_violated
        )

    return GenerationQueryResult(
        query=query,
        answer_preview=_answer_preview(answer_text),
        insufficient_context=answer.insufficient_context,
        answer_facts_found=facts_found,
        answer_facts_total=facts_total,
        answer_fact_recall=answer_fact_recall,
        citation_hit=citation_hit,
        must_not_violated=must_not_violated,
        refusal_detected=refusal_detected,
        generation_pass=generation_pass,
    )


def _score_generation_case(
    case: EvalCase,
    generation_results: tuple[GenerationQueryResult, ...],
    *,
    fact_recall_threshold: float,
) -> tuple[bool, bool, bool, bool, bool]:
    if not generation_results:
        return True, True, True, True, True

    generation_pass = all(result.generation_pass for result in generation_results)
    answer_facts_pass = all(
        result.answer_fact_recall >= fact_recall_threshold
        for result in generation_results
        if result.answer_facts_total > 0
    ) or not any(result.answer_facts_total > 0 for result in generation_results)
    citation_pass = (
        any(result.citation_hit for result in generation_results)
        if case.required_sources
        else True
    )

    if case.category == "negative":
        refusal_pass = all(result.refusal_detected for result in generation_results)
        return generation_pass, True, True, refusal_pass, generation_pass

    refusal_pass = all(not result.refusal_detected for result in generation_results)

    if case.category == "stability" and len(generation_results) > 1:
        pass_flags = {result.generation_pass for result in generation_results}
        fact_scores = [round(result.answer_fact_recall, 2) for result in generation_results]
        stability_pass = len(pass_flags) == 1 and len(set(fact_scores)) <= 1
        generation_pass = generation_pass and stability_pass

    return generation_pass, answer_facts_pass, citation_pass, refusal_pass, generation_pass


def evaluate_query(
    chunks: list[HybridChunk],
    *,
    query: str,
    case: EvalCase,
    top_k: int,
    top_rerank_score: float | None,
) -> QueryEvalResult:
    """Score retrieval output for one query variant.

    Args:
        chunks: Ranked retrieved chunks.
        query: Query string that was executed.
        case: Golden QA case definition.
        top_k: Evaluation cutoff rank.
        top_rerank_score: Best rerank score from retrieval.

    Returns:
        Per-query retrieval metrics.
    """
    limited = chunks[:top_k]
    source_hit, source_hit_rank, matched_sources = _find_source_hit(
        limited,
        case.required_sources,
    )
    facts_found, facts_total, fact_recall = _fact_recall(limited, case.expected_facts)
    forbidden_scope = _negative_forbidden_scope(limited, case.forbidden_scope)
    forbidden_source = _forbidden_source_hit(limited, case.forbidden_sources)
    forbidden_text = _forbidden_text_hit(limited, case.must_not_contain)

    return QueryEvalResult(
        query=query,
        source_hit=source_hit,
        source_hit_rank=source_hit_rank,
        facts_found=facts_found,
        facts_total=facts_total,
        fact_recall=fact_recall,
        top_rerank_score=top_rerank_score,
        matched_sources=matched_sources,
        chunk_count=len(limited),
        forbidden_scope_hit=forbidden_scope or forbidden_source,
        forbidden_text_hit=forbidden_text,
    )


def _score_case(
    case: EvalCase,
    query_results: tuple[QueryEvalResult, ...],
    *,
    fact_recall_threshold: float,
    negative_rerank_ceiling: float,
    generation_results: tuple[GenerationQueryResult, ...] = (),
    include_generation: bool = False,
) -> CaseEvalResult:
    include_retrieval = bool(query_results)

    if include_retrieval and case.category == "negative":
        negative_pass = all(
            not result.forbidden_scope_hit
            and not result.forbidden_text_hit
            and (
                result.chunk_count == 0
                or result.top_rerank_score is None
                or result.top_rerank_score <= negative_rerank_ceiling
            )
            for result in query_results
        )
        retrieval_pass = negative_pass
        source_pass = True
        facts_pass = True
        stability_pass = True
    elif include_retrieval:
        negative_pass = True
        if case.required_sources:
            source_pass = any(result.source_hit for result in query_results)
        else:
            source_pass = True
        facts_pass = all(
            result.fact_recall >= fact_recall_threshold
            for result in query_results
            if result.facts_total > 0
        )
        if not any(result.facts_total > 0 for result in query_results):
            facts_pass = source_pass

        if case.category == "stability" and len(query_results) > 1:
            source_flags = {result.source_hit for result in query_results}
            fact_scores = [round(result.fact_recall, 2) for result in query_results]
            stability_pass = len(source_flags) == 1 and len(set(fact_scores)) <= 1
        else:
            stability_pass = True
        retrieval_pass = source_pass and facts_pass and stability_pass
    else:
        negative_pass = True
        source_pass = True
        facts_pass = True
        stability_pass = True
        retrieval_pass = True

    if include_generation:
        generation_pass, answer_facts_pass, citation_pass, refusal_pass, _ = (
            _score_generation_case(
                case,
                generation_results,
                fact_recall_threshold=fact_recall_threshold,
            )
        )
        overall_pass = retrieval_pass and generation_pass
    else:
        generation_pass = True
        answer_facts_pass = True
        citation_pass = True
        refusal_pass = True
        overall_pass = retrieval_pass

    return CaseEvalResult(
        case_id=case.id,
        title=case.title,
        category=case.category,
        mandatory=case.mandatory,
        query_results=query_results,
        source_pass=source_pass,
        facts_pass=facts_pass,
        negative_pass=negative_pass,
        stability_pass=stability_pass,
        overall_pass=overall_pass,
        generation_results=generation_results,
        generation_pass=generation_pass,
        answer_facts_pass=answer_facts_pass,
        citation_pass=citation_pass,
        refusal_pass=refusal_pass,
    )


def run_eval(
    dataset: EvalDataset,
    *,
    mode: EvalMode = "retrieval",
    retrieval_engine: RetrievalEngine | None = None,
    rag_service: RagAnswerEngine | None = None,
    top_k: int = 8,
    fact_recall_threshold: float = DEFAULT_FACT_RECALL_THRESHOLD,
    negative_rerank_ceiling: float = DEFAULT_NEGATIVE_RERANK_CEILING,
    case_ids: set[str] | None = None,
    categories: set[str] | None = None,
    mandatory_only: bool = False,
) -> EvalReport:
    """Evaluate retrieval and/or generation against golden QA cases.

    Args:
        dataset: Loaded golden QA dataset.
        mode: ``retrieval``, ``generation``, or ``both``.
        retrieval_engine: Engine for retrieval scoring. Required unless mode is
            ``generation`` and the RAG service exposes ``engine``.
        rag_service: Service for generation scoring. Required for ``generation``
            and ``both`` modes.
        top_k: Top-k cutoff used for retrieval scoring and RAG context size.
        fact_recall_threshold: Minimum fact recall for a pass.
        negative_rerank_ceiling: Maximum rerank score allowed for negative cases.
        case_ids: Optional case id filter.
        categories: Optional category filter.
        mandatory_only: When true, evaluate only mandatory cases.

    Returns:
        Aggregated evaluation report.

    Raises:
        ValueError: If required backends are missing for the selected mode.
    """
    if mode in {"retrieval", "both"} and retrieval_engine is None:
        if rag_service is not None and hasattr(rag_service, "engine"):
            retrieval_engine = rag_service.engine  # type: ignore[attr-defined]
        else:
            raise ValueError("retrieval_engine is required for retrieval evaluation")
    if mode in {"generation", "both"} and rag_service is None:
        raise ValueError("rag_service is required for generation evaluation")

    selected = _select_cases(
        dataset,
        case_ids=case_ids,
        categories=categories,
        mandatory_only=mandatory_only,
    )

    case_results: list[CaseEvalResult] = []
    for case in selected:
        per_query: list[QueryEvalResult] = []
        generation_results: list[GenerationQueryResult] = []

        for query in case.all_questions():
            filters = case.filters
            product = (filters.product or None) if filters else None
            project = filters.project if filters else None
            build = filters.build if filters else None

            retrieval = RetrievalResult(chunks=[], top_rerank_score=None)
            if mode in {"retrieval", "both"}:
                assert retrieval_engine is not None
                retrieval = retrieval_engine.retrieve(
                    query,
                    target_product=product,
                    target_project=project,
                    target_build=build,
                    top_k_final=top_k,
                )
                per_query.append(
                    evaluate_query(
                        retrieval.chunks,
                        query=query,
                        case=case,
                        top_k=top_k,
                        top_rerank_score=retrieval.top_rerank_score,
                    )
                )

            if mode in {"generation", "both"}:
                assert rag_service is not None
                answer = rag_service.answer(
                    query,
                    target_product=product,
                    target_project=project,
                    target_build=build,
                    top_k_final=top_k,
                )
                generation_results.append(
                    evaluate_generation(
                        answer,
                        query=query,
                        case=case,
                        fact_recall_threshold=fact_recall_threshold,
                    )
                )

        case_results.append(
            _score_case(
                case,
                tuple(per_query),
                fact_recall_threshold=fact_recall_threshold,
                negative_rerank_ceiling=negative_rerank_ceiling,
                generation_results=tuple(generation_results),
                include_generation=mode in {"generation", "both"},
            )
        )

    return EvalReport(
        dataset_version=dataset.version,
        corpus_built_at=dataset.corpus.built_at,
        top_k=top_k,
        fact_recall_threshold=fact_recall_threshold,
        case_results=tuple(case_results),
        mode=mode,
    )


def run_retrieval_eval(
    engine: RetrievalEngine,
    dataset: EvalDataset,
    *,
    top_k: int = 8,
    fact_recall_threshold: float = DEFAULT_FACT_RECALL_THRESHOLD,
    negative_rerank_ceiling: float = DEFAULT_NEGATIVE_RERANK_CEILING,
    case_ids: set[str] | None = None,
    categories: set[str] | None = None,
    mandatory_only: bool = False,
) -> EvalReport:
    """Evaluate retrieval against all or selected golden QA cases.

    Args:
        engine: Hybrid retrieval engine or compatible mock.
        dataset: Loaded golden QA dataset.
        top_k: Top-k cutoff used for source and fact scoring.
        fact_recall_threshold: Minimum fact recall for a pass.
        negative_rerank_ceiling: Maximum rerank score allowed for negative cases.
        case_ids: Optional case id filter.
        categories: Optional category filter.
        mandatory_only: When true, evaluate only mandatory cases.

    Returns:
        Aggregated evaluation report.
    """
    return run_eval(
        dataset,
        mode="retrieval",
        retrieval_engine=engine,
        top_k=top_k,
        fact_recall_threshold=fact_recall_threshold,
        negative_rerank_ceiling=negative_rerank_ceiling,
        case_ids=case_ids,
        categories=categories,
        mandatory_only=mandatory_only,
    )


def load_dataset_for_eval(
    dataset_path: Path | None = None,
    *,
    validate: bool = True,
) -> EvalDataset:
    """Load the golden QA dataset for evaluation runs.

    Args:
        dataset_path: Optional explicit dataset path.
        validate: Whether to validate against the JSON schema.

    Returns:
        Parsed evaluation dataset.
    """
    return load_qa_dataset(dataset_path=dataset_path, validate=validate)
