#!/usr/bin/env python3
"""CLI entry point for starting the EE-Wiki API server."""

from __future__ import annotations

import argparse
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the EE-Wiki FastAPI server.")
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host (default: config api.host)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: config api.port)",
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
    except EEWikiError as exc:
        logger.error("%s", exc)
        return 1

    host = args.host or config.api.host
    port = args.port or config.api.port

    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn is not installed; run: pip install -e '.[api]'")
        return 1

    logger.info("Starting EE-Wiki API on %s:%s", host, port)
    uvicorn.run("ee_wiki.api.app:create_app", host=host, port=port, factory=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
