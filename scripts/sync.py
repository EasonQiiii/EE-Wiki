#!/usr/bin/env python3
"""CLI entry point for ingest + index in one run (raw → processed → indexes)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ee_wiki.common.cli_summary import print_ingest_run_summary
from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.pipeline import ingest_path
from ee_wiki.knowledge.indexer import build_index_from_processed

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run EE-Wiki ingest then index in one command. "
            "Scans data/raw/ (or a subdirectory), updates data/processed/, "
            "then builds or incrementally updates data/indexes/."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help=(
            "Optional file or directory under data/raw/ "
            "(default: entire data/raw/)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest and rebuild the full index even when fingerprints match",
    )
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Run ingest only; skip index build",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Run index build only; skip ingest",
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
    if args.ingest_only and args.index_only:
        logger.error("Cannot use --ingest-only and --index-only together")
        return 1

    if args.verbose:
        logging.getLogger("ee_wiki").setLevel(logging.DEBUG)

    try:
        config = load_config()
        target = args.path or config.raw_dir
        exit_code = 0

        if not args.index_only:
            ingest_run = ingest_path(target, config, force=args.force)
            for result in ingest_run.ingested:
                print(result.processed.content_path)
                print(result.processed.metadata_path)
            for removed in ingest_run.removed:
                print(f"removed:{removed.content_path}", file=sys.stderr)
            print(
                f"Ingested: {len(ingest_run.ingested)}, "
                f"skipped (unchanged): {len(ingest_run.skipped)}, "
                f"removed (raw deleted): {len(ingest_run.removed)}",
                file=sys.stderr,
            )
            if print_ingest_run_summary(ingest_run, raw_dir=config.raw_dir):
                exit_code = 1

        if not args.ingest_only:
            index_result = build_index_from_processed(config, force=args.force)
            print(
                f"Indexed: {index_result.indexed_documents} document(s), "
                f"skipped (unchanged): {index_result.skipped_documents}, "
                f"removed (processed deleted): {index_result.removed_documents} "
                f"→ {index_result.chunk_count} chunk(s) in {config.indexes_dir}",
                file=sys.stderr,
            )
            if index_result.manifest.built_at:
                print(index_result.manifest.built_at)
    except (EEWikiError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
