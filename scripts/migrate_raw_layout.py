#!/usr/bin/env python3
"""Migrate legacy two-level raw trees to ADR 0011 product/project/build layout.

Default is dry-run (print planned moves only). Pass ``--apply`` to move.

Example::

    python scripts/migrate_raw_layout.py --map logan=iphone,macon=iphone
    python scripts/migrate_raw_layout.py --map logan=iphone --apply

Does not touch ``data/raw/global/``, processed mirrors, indexes, graph, or
FA cache/exports. After apply, rebuild: delete processed+indexes+graph →
ingest → index → build_graph. See docs/usage/ingest.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.migrate_layout import (
    apply_raw_layout_migration,
    format_plan_report,
    parse_project_product_map,
    plan_raw_layout_migration,
)

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the migration CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy data/raw/{project}/... trees to "
            "data/raw/{product}/{project}/... (ADR 0011). "
            "Default is dry-run; pass --apply to execute moves."
        ),
    )
    parser.add_argument(
        "--map",
        dest="map_cli",
        default=None,
        help=(
            "Comma-separated project=product pairs "
            "(required unless --map-file is set), e.g. logan=iphone,macon=iphone"
        ),
    )
    parser.add_argument(
        "--map-file",
        type=Path,
        default=None,
        help="YAML or JSON file with project→product mapping",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute planned moves (default: dry-run only)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Override data/raw directory (default: from config)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run dry-run or apply migration; return process exit code."""
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        raw_dir = args.raw_dir or config.raw_dir
        mapping = parse_project_product_map(
            map_cli=args.map_cli,
            map_file=args.map_file,
        )
        plan = plan_raw_layout_migration(
            raw_dir,
            mapping,
            config.data_layout,
        )
        if plan.empty:
            print(format_plan_report(plan, apply=False))
            logger.warning("No moves planned")
            return 0
        if not args.apply:
            print(format_plan_report(plan, apply=False))
            return 0
        apply_raw_layout_migration(plan)
        print(format_plan_report(plan, apply=True))
    except EEWikiError as exc:
        logger.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
