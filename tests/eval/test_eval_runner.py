"""Tests for retrieval evaluation runner."""

from __future__ import annotations

from dataclasses import dataclass

from ee_wiki.common.config import find_repo_root
from ee_wiki.common.eval_qa import load_qa_dataset
from ee_wiki.common.eval_runner import (
    _fact_in_text,
    evaluate_generation,
    evaluate_query,
    normalize_eval_path,
    run_retrieval_eval,
    source_matches_required,
)
from ee_wiki.common.types import Citation, RagAnswer
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult


def _chunk(
    *,
    content: str,
    target_file: str,
    source_file: str | None = None,
    project: str = "global",
    build: str = "global",
) -> HybridChunk:
    return HybridChunk(
        chunk_id="chunk-1",
        content=content,
        metadata={
            "project": project,
            "build": build,
            "target_file": target_file,
        },
        citation={
            "source_file": source_file or target_file,
            "chunk_id": "chunk-1",
            "page": 1,
            "excerpt": content[:80],
        },
    )


def test_normalize_eval_path_strips_absolute_prefix() -> None:
    path = "/Users/ml/Documents/EE-Wiki/data/processed/global/datasheet/STM32F407ZGT6.md"
    assert normalize_eval_path(path) == "data/processed/global/datasheet/STM32F407ZGT6.md"


def test_source_matches_required_across_raw_and_processed() -> None:
    chunk = _chunk(
        content="168 MHz flash",
        target_file="data/processed/global/datasheet/STM32F407ZGT6.md",
        source_file="/repo/data/raw/global/datasheet/STM32F407ZGT6.pdf",
    )
    required = "data/processed/global/datasheet/STM32F407ZGT6.md"
    assert source_matches_required(required, chunk)


@dataclass
class _FakeEngine:
    responses: dict[str, RetrievalResult]

    def retrieve(
        self,
        query: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
    ) -> RetrievalResult:
        del target_project, target_build, document_type, top_k_final
        return self.responses[query]


def test_run_retrieval_eval_scores_source_and_facts() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-001")
    chunk = _chunk(
        content="Maximum CPU frequency 168 MHz, Flash 1 Mbyte, SRAM 192 Kbytes",
        target_file=case.required_sources[0],
    )
    engine = _FakeEngine(
        responses={
            case.question: RetrievalResult(chunks=[chunk], top_rerank_score=2.5),
        }
    )

    report = run_retrieval_eval(engine, dataset, case_ids={"Q-001"}, top_k=3)

    assert len(report.case_results) == 1
    result = report.case_results[0]
    assert result.overall_pass is True
    assert result.source_pass is True
    assert result.facts_pass is True
    assert result.query_results[0].source_hit_rank == 1
    assert result.query_results[0].facts_found == 3


def test_negative_case_fails_on_forbidden_scope() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-019")
    chunk = _chunk(
        content="PMIC VBAT connects to U0902",
        target_file="data/processed/apollo/evt/note/fake.md",
        project="apollo",
        build="evt",
    )
    engine = _FakeEngine(
        responses={
            case.question: RetrievalResult(chunks=[chunk], top_rerank_score=1.0),
        }
    )

    report = run_retrieval_eval(engine, dataset, case_ids={"Q-019"}, top_k=3)

    result = report.case_results[0]
    assert result.overall_pass is False
    assert result.negative_pass is False


def test_evaluate_query_reports_fact_recall() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-002")
    chunk = _chunk(
        content="MP2359 buck step-down regulator 1.2 A 1.4 MHz 24 V",
        target_file=case.required_sources[0],
    )
    scored = evaluate_query(
        [chunk],
        query=case.question,
        case=case,
        top_k=3,
        top_rerank_score=1.5,
    )
    assert scored.fact_recall >= 0.6


def test_evaluate_generation_positive_case() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-001")
    answer = RagAnswer(
        answer="STM32F407ZGT6 runs at 168 MHz with 1 Mbyte Flash and 192 Kbytes SRAM.",
        citations=[
            Citation(
                source_file="data/raw/global/datasheet/STM32F407ZGT6.pdf",
                chunk_id="stm32__1",
                excerpt="168 MHz",
            )
        ],
        insufficient_context=False,
    )
    scored = evaluate_generation(
        answer,
        query=case.question,
        case=case,
        fact_recall_threshold=0.6,
    )
    assert scored.generation_pass is True
    assert scored.citation_hit is True
    assert scored.refusal_detected is False


def test_fact_matching_ignores_spacing() -> None:
    assert _fact_in_text("1.2 A", "peak output 1.2A at 24V")
    assert _fact_in_text("1.4 MHz", "fixed 1.4MHz frequency")


def test_forbidden_scope_only_when_configured() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-018")
    chunk = _chunk(
        content="STM32F407 MCU specifications",
        target_file="data/processed/global/datasheet/STM32F407ZGT6.md",
        project="global",
        build="global",
    )
    scored = evaluate_query(
        [chunk],
        query=case.question,
        case=case,
        top_k=3,
        top_rerank_score=-2.067,
    )
    assert scored.forbidden_scope_hit is False


def test_evaluate_generation_negative_case() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    case = next(item for item in dataset.cases if item.id == "Q-019")
    answer = RagAnswer(
        answer="知识库中未找到相关内容，无法回答该问题。",
        citations=[],
        insufficient_context=True,
    )
    scored = evaluate_generation(
        answer,
        query=case.question,
        case=case,
        fact_recall_threshold=0.6,
    )
    assert scored.generation_pass is True
    assert scored.refusal_detected is True
