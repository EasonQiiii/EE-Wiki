#!/usr/bin/env python3
"""CLI entry point for building hybrid retrieval indexes from processed documents."""

from __future__ import annotations

import argparse
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.knowledge.indexer import build_index_from_processed

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or rebuild EE-Wiki hybrid indexes (chunks + embeddings + BM25) "
            "from data/processed/ into data/indexes/."
        ),
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
        result = build_index_from_processed(config)
    except (EEWikiError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    print(
        f"Indexed: {result.chunk_count} chunk(s) → {config.indexes_dir}",
        file=sys.stderr,
    )
    print(result.manifest.built_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
