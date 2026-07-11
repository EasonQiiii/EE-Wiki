#!/usr/bin/env python3
"""CLI entry point for ingesting raw documents into data/processed/.

Usage guide: docs/usage/ingest.md
"""

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

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest raw documents into EE-Wiki processed mirror. "
            "Without a path, scans all of data/raw/, skips unchanged files, "
            "and removes processed outputs whose raw source was deleted."
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
        help="Re-ingest all files even when source mtime and size are unchanged",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (e.g. transformers load progress)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger("ee_wiki").setLevel(logging.DEBUG)
    try:
        config = load_config()
        target = args.path or config.raw_dir
        run = ingest_path(target, config, force=args.force)
    except EEWikiError as exc:
        logger.error("%s", exc)
        return 1

    for result in run.ingested:
        print(result.processed.content_path)
        print(result.processed.metadata_path)

    for removed in run.removed:
        print(f"removed:{removed.content_path}", file=sys.stderr)

    print(
        f"Ingested: {len(run.ingested)}, skipped (unchanged): {len(run.skipped)}, "
        f"removed (raw deleted): {len(run.removed)}",
        file=sys.stderr,
    )
    if print_ingest_run_summary(run, raw_dir=config.raw_dir):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
