#!/usr/bin/env python3
"""CLI entry point for hybrid retrieval over indexed documents."""

from __future__ import annotations

import argparse
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.retrieval.hybrid import HybridRagEngine

logger = get_logger(__name__)

PREVIEW_CHARS = 200


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run hybrid retrieval (embedding + BM25 + rerank) over data/indexes/ "
            "and print ranked chunks with citations."
        ),
    )
    parser.add_argument("query", help="Natural language or keyword search string")
    parser.add_argument(
        "--project",
        default=None,
        help="Metadata filter: project name (e.g. logan)",
    )
    parser.add_argument(
        "--build",
        default=None,
        help="Metadata filter: build name (e.g. p1)",
    )
    parser.add_argument(
        "--document-type",
        default=None,
        dest="document_type",
        help="Metadata filter: document type (e.g. schematic, engineering_note)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        dest="top_k",
        help="Number of final chunks to return (default: config retrieval.top_k_final)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def _format_chunk(index: int, chunk) -> str:
    citation = chunk.citation
    preview = chunk.content[:PREVIEW_CHARS].replace("\n", " ")
    if len(chunk.content) > PREVIEW_CHARS:
        preview += "..."
    lines = [
        f"[{index}] chunk_id={chunk.chunk_id}",
        f"    source_file={citation.get('source_file', '')}",
        f"    page={citation.get('page', 0)}",
        f"    excerpt={citation.get('excerpt', '')}",
        f"    preview={preview}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger("ee_wiki").setLevel(logging.DEBUG)
    try:
        config = load_config()
        engine = HybridRagEngine(config)
        engine.load_index()
        results = engine.retrieve(
            args.query,
            target_project=args.project,
            target_build=args.build,
            document_type=args.document_type,
            top_k_final=args.top_k,
        )
    except (EEWikiError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    if not results:
        print("No matching chunks found.", file=sys.stderr)
        return 0

    print(f"Retrieved {len(results)} chunk(s) for query: {args.query!r}", file=sys.stderr)
    for index, chunk in enumerate(results, start=1):
        print(_format_chunk(index, chunk))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
