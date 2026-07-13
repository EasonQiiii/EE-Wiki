#!/usr/bin/env python3
"""CLI entry point for building the V3 knowledge graph from index artifacts."""

from __future__ import annotations

import argparse
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.graph import build_and_save_graph

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the EE-Wiki knowledge graph from data/indexes/ "
            "(chunks.jsonl + components.json + cases.json) into data/graph/ "
            "(manifest.json + nodes.jsonl + edges.jsonl)."
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
        result = build_and_save_graph(config)
    except (EEWikiError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    print(
        f"Graph: {result.node_count} node(s), {result.edge_count} edge(s) "
        f"→ {result.graph_dir}",
        file=sys.stderr,
    )
    print(result.manifest.built_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
