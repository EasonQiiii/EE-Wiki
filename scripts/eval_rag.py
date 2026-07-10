#!/usr/bin/env python3
"""CLI entry point for RAG evaluation against docs/eval/qa.yaml."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.eval_runner import (
    DEFAULT_FACT_RECALL_THRESHOLD,
    DEFAULT_NEGATIVE_RERANK_CEILING,
    EvalMode,
    build_eval_config,
    load_dataset_for_eval,
    run_eval,
    run_retrieval_eval,
)
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.service import RagService
from ee_wiki.retrieval.hybrid import HybridRagEngine

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate EE-Wiki RAG against the golden QA dataset. "
            "Supports retrieval-only, generation-only, or both."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "generation", "both"],
        default="retrieval",
        help="Evaluation mode (default: retrieval)",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to qa.yaml (default: docs/eval/qa.yaml)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Top-k cutoff for scoring (default: config retrieval.top_k_final)",
    )
    parser.add_argument(
        "--fact-threshold",
        type=float,
        default=DEFAULT_FACT_RECALL_THRESHOLD,
        help="Minimum fact recall for a pass",
    )
    parser.add_argument(
        "--negative-rerank-ceiling",
        type=float,
        default=DEFAULT_NEGATIVE_RERANK_CEILING,
        help="Max top rerank score allowed for negative retrieval cases",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        dest="cases",
        help="Evaluate only this case id (repeatable, e.g. Q-001)",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        dest="categories",
        help="Evaluate only this category (repeatable)",
    )
    parser.add_argument(
        "--mandatory-only",
        action="store_true",
        help="Evaluate only mandatory cases",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON report to stdout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this file",
    )
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        help="Exit 1 when mandatory/negative thresholds are not met",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def _format_text_report(report) -> str:
    mode = report.mode
    lines = [
        f"EE-Wiki RAG eval ({mode})",
        f"dataset={report.dataset_version} corpus={report.corpus_built_at} top_k={report.top_k}",
        (
            f"summary: passed {report.passed_cases}/{report.total_cases} "
            f"mandatory={report.mandatory_pass_rate:.0%} "
            f"negative={report.negative_pass_rate:.0%} "
            f"source_hit={report.source_hit_rate:.0%} "
            f"generation={report.generation_pass_rate:.0%}"
        ),
        "",
    ]
    if mode in {"retrieval", "both"}:
        lines.append(
            f"{'ID':<8} {'PASS':<5} {'SRC':<4} {'FACT':<5} {'STAB':<5} {'NEG':<4} Title"
        )
    else:
        lines.append(f"{'ID':<8} {'PASS':<5} {'GEN':<4} {'ANS':<4} {'CIT':<4} {'REF':<4} Title")
    lines.append("-" * 80)

    for case in report.case_results:
        if mode in {"retrieval", "both"}:
            lines.append(
                f"{case.case_id:<8} "
                f"{'Y' if case.overall_pass else 'N':<5} "
                f"{'Y' if case.source_pass else 'N':<4} "
                f"{'Y' if case.facts_pass else 'N':<5} "
                f"{'Y' if case.stability_pass else 'N':<5} "
                f"{'Y' if case.negative_pass else 'N':<4} "
                f"{case.title}"
            )
            for query in case.query_results:
                rank = query.source_hit_rank if query.source_hit_rank is not None else "-"
                rerank = (
                    f"{query.top_rerank_score:.3f}"
                    if query.top_rerank_score is not None
                    else "None"
                )
                lines.append(
                    f"  - hit@{report.top_k}={query.source_hit} rank={rank} "
                    f"facts={query.facts_found}/{query.facts_total} rerank={rerank}"
                )
                lines.append(f"    Q: {query.query}")
        else:
            lines.append(
                f"{case.case_id:<8} "
                f"{'Y' if case.overall_pass else 'N':<5} "
                f"{'Y' if case.generation_pass else 'N':<4} "
                f"{'Y' if case.answer_facts_pass else 'N':<4} "
                f"{'Y' if case.citation_pass else 'N':<4} "
                f"{'Y' if case.refusal_pass else 'N':<4} "
                f"{case.title}"
            )

        if case.generation_results and mode in {"generation", "both"}:
            for item in case.generation_results:
                lines.append(
                    f"  - gen_pass={item.generation_pass} "
                    f"facts={item.answer_facts_found}/{item.answer_facts_total} "
                    f"citation={item.citation_hit} refusal={item.refusal_detected}"
                )
                lines.append(f"    Q: {item.query}")
                lines.append(f"    A: {item.answer_preview}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger("ee_wiki").setLevel(logging.DEBUG)

    mode: EvalMode = args.mode
    try:
        config = build_eval_config(load_config())
        dataset = load_dataset_for_eval(args.dataset)
        top_k = args.top_k or config.retrieval.top_k_final

        retrieval_engine = None
        rag_service = None
        if mode in {"retrieval", "both"}:
            retrieval_engine = HybridRagEngine(config)
            retrieval_engine.load_index()
        if mode in {"generation", "both"}:
            rag_service = RagService.from_config(config)
            if mode == "generation":
                rag_service.engine.load_index()
            elif retrieval_engine is not None:
                rag_service.engine = retrieval_engine

        if mode == "retrieval":
            assert retrieval_engine is not None
            report = run_retrieval_eval(
                retrieval_engine,
                dataset,
                top_k=top_k,
                fact_recall_threshold=args.fact_threshold,
                negative_rerank_ceiling=args.negative_rerank_ceiling,
                case_ids=set(args.cases) if args.cases else None,
                categories=set(args.categories) if args.categories else None,
                mandatory_only=args.mandatory_only,
            )
        else:
            report = run_eval(
                dataset,
                mode=mode,
                retrieval_engine=retrieval_engine,
                rag_service=rag_service,
                top_k=top_k,
                fact_recall_threshold=args.fact_threshold,
                negative_rerank_ceiling=args.negative_rerank_ceiling,
                case_ids=set(args.cases) if args.cases else None,
                categories=set(args.categories) if args.categories else None,
                mandatory_only=args.mandatory_only,
            )
    except (EEWikiError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    payload = report.to_dict()
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote report to {args.output}", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))

    if args.fail_on_threshold and not report.meets_thresholds():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
