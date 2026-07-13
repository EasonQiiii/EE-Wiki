#!/usr/bin/env python3
"""CLI entry point for evaluating V3 P4 engineering rules."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ee_wiki.common.config import load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.graph.power_tree import open_power_query
from ee_wiki.graph.query import open_query
from ee_wiki.graph.store import GraphStoreError, JsonlGraphStore, graph_exists
from ee_wiki.knowledge.indexer.case_index import CaseIndexError, load_case_index
from ee_wiki.rules.engine import open_rule_engine
from ee_wiki.rules.errors import RulePackError

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate EE-Wiki engineering rules (config/rules/*.yaml) against "
            "the knowledge graph and optional case index."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List rules instead of evaluating",
    )
    parser.add_argument("--project", default=None, help="Optional project filter")
    parser.add_argument("--build", default=None, help="Optional build filter")
    parser.add_argument(
        "--rule",
        action="append",
        dest="rules",
        default=None,
        help="Rule id to evaluate (repeatable); default = all enabled",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled rules",
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
        if not config.rules.enabled:
            logger.error("rules.enabled is false in config")
            return 1
        if not graph_exists(config.graph_dir):
            logger.error(
                "Knowledge graph not found under %s. "
                "Run python scripts/build_graph.py after indexing.",
                config.graph_dir,
            )
            return 1
        graph = JsonlGraphStore().load_graph(config.graph_dir)
        gq = open_query(
            graph,
            layout=config.data_layout,
            scope_inheritance=config.graph.scope_inheritance,
        )
        power = open_power_query(gq) if config.graph.power_tree else None
        cases = None
        try:
            cases = load_case_index(config.indexes_dir)
        except CaseIndexError as exc:
            logger.warning("Case index unavailable: %s", exc)
        engine = open_rule_engine(
            gq,
            config.rules_pack_dir,
            power_query=power,
            case_index=cases,
        )
    except (EEWikiError, GraphStoreError, RulePackError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    if args.list:
        rules = engine.list_rules(include_disabled=args.include_disabled)
        payload = {
            "pack_dir": engine.pack.pack_dir,
            "rules": [r.to_dict() for r in rules],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    summary = engine.evaluate_summary(
        rule_ids=args.rules,
        project=args.project,
        build=args.build,
        include_disabled=args.include_disabled,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    counts = summary.get("counts") or {}
    fail_count = int(counts.get("fail", 0))
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
