#!/usr/bin/env python3
"""CLI entry point for the EE-Wiki MCP tool server."""

from __future__ import annotations

import argparse
import logging
import sys

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the EE-Wiki MCP tool server.")
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
        from ee_wiki.tools.mcp_server import run_stdio
    except ImportError as exc:
        logger.error("%s", exc)
        return 1
    except EEWikiError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Starting EE-Wiki MCP server (stdio)")
    run_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
