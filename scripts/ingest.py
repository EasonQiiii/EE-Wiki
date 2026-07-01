#!/usr/bin/env python3
"""CLI entry point for ingesting raw documents into data/processed/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.pipeline import ingest_path

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest raw documents into EE-Wiki processed mirror.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="File or directory under data/raw/ to ingest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        results = ingest_path(args.path, config)
    except EEWikiError as exc:
        logger.error("%s", exc)
        return 1

    for result in results:
        print(result.processed.content_path)
        print(result.processed.metadata_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
