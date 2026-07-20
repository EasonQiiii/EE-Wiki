"""Orchestrate loading and evaluating engineering rules (V3 P4)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.graph.power_tree import PowerTreeQuery
from ee_wiki.graph.query import GraphQuery
from ee_wiki.knowledge.indexer.case_index import CaseIndex
from ee_wiki.rules.checks import (
    check_fa_recurrence,
    check_interface_naming,
    check_power_tree_flags,
    check_rail_presence,
)
from ee_wiki.rules.loader import load_rule_pack
from ee_wiki.rules.models import RuleDefinition, RulePack, RuleResult

_CHECK_REGISTRY: dict[str, Callable[..., RuleResult]] = {
    "rail_presence": check_rail_presence,
    "power_tree_flags": check_power_tree_flags,
    "interface_naming": check_interface_naming,
    "fa_recurrence": check_fa_recurrence,
}


class RuleEngine:
    """Evaluate config-driven rules against a loaded graph (and optional cases)."""

    def __init__(
        self,
        pack: RulePack,
        graph_query: GraphQuery,
        *,
        power_query: PowerTreeQuery | None = None,
        case_index: CaseIndex | None = None,
    ) -> None:
        """Bind a rule pack to graph / power / case evaluation backends.

        Args:
            pack: Loaded rule definitions.
            graph_query: Scope-aware graph query handle.
            power_query: Optional power-tree query (for flag checks).
            case_index: Optional debug-case index (for FA recurrence).
        """
        self.pack = pack
        self.graph_query = graph_query
        self.power_query = power_query
        self.case_index = case_index
        self.layout: DataLayoutConfig = graph_query.layout

    def list_rules(self, *, include_disabled: bool = False) -> list[RuleDefinition]:
        """Return rule definitions from the pack.

        Args:
            include_disabled: When true, include rules with ``enabled: false``.

        Returns:
            Rule definitions in pack order.
        """
        if include_disabled:
            return list(self.pack.rules)
        return self.pack.enabled_rules()

    def evaluate(
        self,
        *,
        rule_ids: list[str] | None = None,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        include_disabled: bool = False,
    ) -> list[RuleResult]:
        """Evaluate selected (or all enabled) rules in scope.

        Args:
            rule_ids: Optional subset of rule ids. Unknown ids yield a fail result.
            product: Optional product filter.
            project: Optional project filter.
            build: Optional build filter.
            include_disabled: Evaluate disabled rules when explicitly requested.

        Returns:
            One :class:`RuleResult` per evaluated rule.
        """
        by_id = self.pack.by_id()
        if rule_ids is not None:
            selected: list[RuleDefinition | None] = []
            for rid in rule_ids:
                selected.append(by_id.get(rid))
            results: list[RuleResult] = []
            for rid, rule in zip(rule_ids, selected, strict=True):
                if rule is None:
                    results.append(
                        RuleResult(
                            rule_id=rid,
                            status="fail",
                            message=f"Unknown rule id: {rid}",
                            details={"error": "unknown_rule"},
                        )
                    )
                    continue
                if not rule.enabled and not include_disabled:
                    results.append(
                        RuleResult(
                            rule_id=rule.id,
                            name=rule.name,
                            severity=rule.severity,
                            status="insufficient",
                            message=f"Rule {rule.id!r} is disabled",
                            details={"enabled": False},
                        )
                    )
                    continue
                results.append(
                    self._evaluate_one(
                        rule, product=product, project=project, build=build
                    )
                )
            return results

        rules = (
            list(self.pack.rules)
            if include_disabled
            else self.pack.enabled_rules()
        )
        return [
            self._evaluate_one(rule, product=product, project=project, build=build)
            for rule in rules
        ]

    def evaluate_summary(
        self,
        *,
        rule_ids: list[str] | None = None,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        include_disabled: bool = False,
    ) -> dict[str, Any]:
        """Evaluate rules and return a JSON-serializable summary payload.

        Args:
            rule_ids: Optional subset of rule ids.
            product: Optional product filter.
            project: Optional project filter.
            build: Optional build filter.
            include_disabled: Include disabled rules when true.

        Returns:
            Dict with ``results``, counts, and scope fields.
        """
        results = self.evaluate(
            rule_ids=rule_ids,
            product=product,
            project=project,
            build=build,
            include_disabled=include_disabled,
        )
        counts = {"pass": 0, "fail": 0, "insufficient": 0}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return {
            "product": product,
            "project": project,
            "build": build,
            "pack_dir": self.pack.pack_dir,
            "counts": counts,
            "results": [r.to_dict() for r in results],
            "limitations": (
                "Engineering rules are heuristic checks over the knowledge graph "
                "and case index — not a full PCB DRC or CAD netlist verifier."
            ),
        }

    def _evaluate_one(
        self,
        rule: RuleDefinition,
        *,
        product: str | None,
        project: str | None,
        build: str | None,
    ) -> RuleResult:
        if rule.check_type not in _CHECK_REGISTRY:
            return RuleResult(
                rule_id=rule.id,
                name=rule.name,
                severity=rule.severity,
                status="fail",
                message=f"Unsupported check type: {rule.check_type!r}",
                details={"check_type": rule.check_type},
            )
        if rule.check_type == "rail_presence":
            return check_rail_presence(
                rule,
                graph_query=self.graph_query,
                product=product,
                project=project,
                build=build,
            )
        if rule.check_type == "power_tree_flags":
            return check_power_tree_flags(
                rule,
                power_query=self.power_query,
                product=product,
                project=project,
                build=build,
            )
        if rule.check_type == "interface_naming":
            return check_interface_naming(
                rule,
                graph_query=self.graph_query,
                product=product,
                project=project,
                build=build,
            )
        if rule.check_type == "fa_recurrence":
            return check_fa_recurrence(
                rule,
                case_index=self.case_index,
                graph_query=self.graph_query,
                product=product,
                project=project,
                build=build,
            )
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="fail",
            message=f"No handler for check type: {rule.check_type!r}",
        )


def open_rule_engine(
    graph_query: GraphQuery,
    pack_dir: Path,
    *,
    power_query: PowerTreeQuery | None = None,
    case_index: CaseIndex | None = None,
) -> RuleEngine:
    """Load a rule pack and return a bound :class:`RuleEngine`.

    Args:
        graph_query: Scope-aware graph query handle.
        pack_dir: Directory of YAML rule files.
        power_query: Optional power-tree query.
        case_index: Optional debug-case index.

    Returns:
        Configured rule engine.

    Raises:
        RulePackError: If the pack cannot be loaded.
    """
    pack = load_rule_pack(pack_dir)
    return RuleEngine(
        pack,
        graph_query,
        power_query=power_query,
        case_index=case_index,
    )
