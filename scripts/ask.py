#!/usr/bin/env python3
"""CLI entry point for end-to-end RAG (retrieve + generate)."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.service import RagService

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run EE-Wiki RAG: hybrid retrieval + local LLM answer with citations.",
    )
    parser.add_argument("question", help="User question")
    parser.add_argument("--project", default=None, help="Metadata filter: project name")
    parser.add_argument("--build", default=None, help="Metadata filter: build name")
    parser.add_argument(
        "--document-type",
        default=None,
        dest="document_type",
        help="Metadata filter: document type",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        dest="top_k",
        help="Number of retrieved chunks to use",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of plain text",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger("ee_wiki").setLevel(logging.DEBUG)
    try:
        config = load_config()
        service = RagService.from_config(config)
        result = service.answer(
            args.question,
            target_project=args.project,
            target_build=args.build,
            document_type=args.document_type,
            top_k_final=args.top_k,
        )
    except (EEWikiError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    if args.json:
        payload = {
            "answer": result.answer,
            "insufficient_context": result.insufficient_context,
            "citations": [
                {
                    "source_file": citation.source_file,
                    "chunk_id": citation.chunk_id,
                    "page": citation.page,
                    "excerpt": citation.excerpt,
                }
                for citation in result.citations
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(result.answer)
    if result.citations:
        print("\n--- Citations ---", file=sys.stderr)
        for index, citation in enumerate(result.citations, start=1):
            print(
                f"[{index}] {citation.source_file} "
                f"(chunk_id={citation.chunk_id}, page={citation.page})",
                file=sys.stderr,
            )
            if citation.excerpt:
                print(f"    excerpt: {citation.excerpt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
