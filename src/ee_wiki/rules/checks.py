"""Built-in engineering rule check implementations (V3 P4)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ee_wiki.graph.models import EDGE_DERIVED_FROM, NODE_NET, NODE_RAIL, KnowledgeGraph
from ee_wiki.graph.power import is_ground_rail, is_rail_like_net
from ee_wiki.graph.power_tree import PowerTreeQuery
from ee_wiki.graph.query import GraphQuery
from ee_wiki.knowledge.indexer.case_index import CaseIndex, DebugCaseRecord
from ee_wiki.rules.models import RuleCitation, RuleDefinition, RuleResult


def _net_name(node_attrs: dict[str, Any], node_id: str) -> str:
    return str(node_attrs.get("name") or node_attrs.get("key") or node_id)


def _normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


def check_rail_presence(
    rule: RuleDefinition,
    *,
    graph_query: GraphQuery,
    project: str | None,
    build: str | None,
) -> RuleResult:
    """Require Rail nodes for rail-like Net names in scope."""
    params = rule.params
    skip_ground = bool(params.get("skip_ground", True))
    nets = graph_query.filter_by_scope(
        project=project,
        build=build,
        node_types={NODE_NET},
    )
    rails = graph_query.filter_by_scope(
        project=project,
        build=build,
        node_types={NODE_RAIL},
    )
    rail_keys = {
        (
            str(r.get("project", "")),
            str(r.get("build", "")),
            _normalize_token(_net_name(r.get("attributes") or {}, str(r.get("id", "")))),
        )
        for r in rails
    }

    # Also accept derived_from rail_of_net links as evidence
    graph: KnowledgeGraph = graph_query.graph
    for edge in graph.edges:
        if edge.type != EDGE_DERIVED_FROM:
            continue
        if (edge.attributes or {}).get("kind") != "rail_of_net":
            continue
        rail = graph.nodes.get(edge.source)
        net = graph.nodes.get(edge.target)
        if rail is None or net is None or rail.type != NODE_RAIL:
            continue
        name = _normalize_token(_net_name(rail.attributes, rail.id))
        rail_keys.add((rail.project, rail.build, name))

    candidates: list[dict[str, Any]] = []
    for net in nets:
        attrs = net.get("attributes") or {}
        name = _net_name(attrs if isinstance(attrs, dict) else {}, str(net.get("id", "")))
        if not is_rail_like_net(name):
            continue
        if skip_ground and is_ground_rail(name):
            continue
        candidates.append(net)

    if not candidates:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="No rail-like nets found in scope; cannot evaluate rail presence",
            details={"rail_like_net_count": 0},
        )

    missing: list[RuleCitation] = []
    for net in candidates:
        attrs = net.get("attributes") or {}
        name = _net_name(attrs if isinstance(attrs, dict) else {}, str(net.get("id", "")))
        key = (
            str(net.get("project", "")),
            str(net.get("build", "")),
            _normalize_token(name),
        )
        if key not in rail_keys:
            missing.append(
                RuleCitation(
                    kind="graph_node",
                    ref=str(net.get("id", "")),
                    project=str(net.get("project", "")),
                    build=str(net.get("build", "")),
                    excerpt=f"Rail-like net {name!r} has no matching Rail node",
                )
            )

    if missing:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="fail",
            message=(
                f"{len(missing)} rail-like net(s) lack a corresponding Rail node "
                f"(of {len(candidates)} candidate nets)"
            ),
            citations=missing,
            details={
                "candidate_count": len(candidates),
                "missing_count": len(missing),
            },
        )

    return RuleResult(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        status="pass",
        message=f"All {len(candidates)} rail-like net(s) have matching Rail nodes",
        details={"candidate_count": len(candidates)},
    )


def check_power_tree_flags(
    rule: RuleDefinition,
    *,
    power_query: PowerTreeQuery | None,
    project: str | None,
    build: str | None,
) -> RuleResult:
    """Map power-tree diagnostic flags to rule fail/pass/insufficient."""
    if power_query is None:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="Power-tree query unavailable (graph.power_tree off or graph missing)",
        )

    fail_codes_raw = rule.params.get("fail_codes")
    if isinstance(fail_codes_raw, list) and fail_codes_raw:
        fail_codes = {str(c) for c in fail_codes_raw}
    else:
        fail_codes = {"missing_supplier", "multi_supplier", "missing_parent_rail"}

    flags = power_query.flags(project=project, build=build)
    matching = [f for f in flags if f.code in fail_codes]

    rails = power_query.graph_query.filter_by_scope(
        project=project,
        build=build,
        node_types={NODE_RAIL},
    )
    if not rails and not matching:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="No Rail nodes in scope; power-tree flags not applicable",
            details={"flag_count": 0},
        )

    if matching:
        citations = [
            RuleCitation(
                kind="graph_node",
                ref=nid,
                project=flag.project,
                build=flag.build,
                excerpt=f"{flag.code}: {flag.message}",
            )
            for flag in matching
            for nid in (flag.node_ids or [""])
            if nid
        ]
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="fail",
            message=f"{len(matching)} power-tree flag(s) in scope",
            citations=citations,
            details={
                "flags": [f.to_dict() for f in matching],
                "flag_count": len(matching),
            },
        )

    return RuleResult(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        status="pass",
        message="No configured power-tree flags in scope",
        details={"flag_count": 0, "rail_count": len(rails)},
    )


def check_interface_naming(
    rule: RuleDefinition,
    *,
    graph_query: GraphQuery,
    project: str | None,
    build: str | None,
) -> RuleResult:
    """Require PREFIX_SIGNAL form for nets with known bus family prefixes."""
    prefixes_raw = rule.params.get("family_prefixes")
    if isinstance(prefixes_raw, list) and prefixes_raw:
        prefixes = [str(p).strip().upper() for p in prefixes_raw if str(p).strip()]
    else:
        prefixes = ["I2C", "SPI", "UART", "USART", "USB", "CAN", "MDIO"]
    require_suffix = bool(rule.params.get("require_suffix", True))

    nets = graph_query.filter_by_scope(
        project=project,
        build=build,
        node_types={NODE_NET},
    )

    # Longer prefixes first so USART wins over UART when both listed.
    prefixes_sorted = sorted(prefixes, key=len, reverse=True)
    candidates: list[tuple[dict[str, Any], str, str]] = []
    for net in nets:
        attrs = net.get("attributes") or {}
        name = _net_name(attrs if isinstance(attrs, dict) else {}, str(net.get("id", "")))
        upper = name.upper().removeprefix("NET_")
        for prefix in prefixes_sorted:
            if upper == prefix or upper.startswith(prefix + "_"):
                candidates.append((net, name, prefix))
                break

    if not candidates:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="No interface-family nets found in scope",
            details={"family_prefixes": prefixes},
        )

    violations: list[RuleCitation] = []
    for net, name, prefix in candidates:
        upper = name.upper().removeprefix("NET_")
        ok = True
        if require_suffix:
            # Must be PREFIX_SIGNAL with non-empty signal token(s)
            if not upper.startswith(prefix + "_"):
                ok = False
            else:
                rest = upper[len(prefix) + 1 :]
                if not rest or not re.fullmatch(r"[A-Z0-9]+(?:_[A-Z0-9]+)*", rest):
                    ok = False
        if not ok:
            violations.append(
                RuleCitation(
                    kind="graph_node",
                    ref=str(net.get("id", "")),
                    project=str(net.get("project", "")),
                    build=str(net.get("build", "")),
                    excerpt=(
                        f"Interface net {name!r} should use {prefix}_SIGNAL form"
                    ),
                )
            )

    if violations:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="fail",
            message=(
                f"{len(violations)} interface net(s) violate naming convention "
                f"(of {len(candidates)} candidates)"
            ),
            citations=violations,
            details={
                "candidate_count": len(candidates),
                "violation_count": len(violations),
            },
        )

    return RuleResult(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        status="pass",
        message=f"All {len(candidates)} interface-family net(s) follow naming convention",
        details={"candidate_count": len(candidates)},
    )


def _case_in_scope(
    case: DebugCaseRecord,
    *,
    project: str | None,
    build: str | None,
    allowed: set[tuple[str, str]] | None,
) -> bool:
    if allowed is not None:
        return (case.project, case.build) in allowed
    if project and case.project != project:
        return False
    if build and case.build != build:
        return False
    return True


def _cases_in_scope(
    cases: tuple[DebugCaseRecord, ...] | list[DebugCaseRecord],
    *,
    graph_query: GraphQuery,
    project: str | None,
    build: str | None,
) -> list[DebugCaseRecord]:
    """Filter cases by project/build with graph-compatible inheritance.

    When only ``project`` is set, include all builds of that project (not just
    ``common``). When ``project`` and ``build`` are both set, use the same
    scope expansion as graph queries.
    """
    if not project and not build:
        return list(cases)
    if project and not build:
        return [c for c in cases if c.project == project]
    allowed = graph_query._allowed_scopes(project=project, build=build)
    return [
        c
        for c in cases
        if _case_in_scope(c, project=project, build=build, allowed=allowed)
    ]


def check_fa_recurrence(
    rule: RuleDefinition,
    *,
    case_index: CaseIndex | None,
    graph_query: GraphQuery,
    project: str | None,
    build: str | None,
) -> RuleResult:
    """Flag symptoms/parts that recur across multiple builds."""
    if case_index is None or not case_index.cases:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="No debug cases available; cannot evaluate FA recurrence",
        )

    min_builds = int(rule.params.get("min_builds", 2))
    match_on_raw = rule.params.get("match_on")
    if isinstance(match_on_raw, list) and match_on_raw:
        match_on = {str(m) for m in match_on_raw}
    else:
        match_on = {"symptom", "suspected_parts"}

    scoped = _cases_in_scope(
        case_index.cases,
        graph_query=graph_query,
        project=project,
        build=build,
    )
    if not scoped:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="insufficient",
            message="No debug cases in scope",
            details={"case_count": 0},
        )

    # Recurrence needs cross-build visibility: when a single build is requested,
    # still scan the whole project for matching signals.
    if project:
        pool = [c for c in case_index.cases if c.project == project]
    else:
        pool = list(scoped)

    groups: dict[tuple[str, str], list[DebugCaseRecord]] = defaultdict(list)

    for case in pool:
        if "symptom" in match_on and case.symptom.strip():
            key = ("symptom", _normalize_token(case.symptom))
            groups[key].append(case)
        if "suspected_parts" in match_on:
            for part in case.suspected_parts:
                token = _normalize_token(part)
                if token:
                    groups[("suspected_parts", token)].append(case)

    recurrent: list[tuple[str, str, list[DebugCaseRecord]]] = []
    for (kind, token), cases in groups.items():
        builds = {c.build for c in cases}
        if len(builds) >= min_builds:
            # Deduplicate cases by case_id+source
            unique: dict[str, DebugCaseRecord] = {}
            for c in cases:
                unique[f"{c.case_id}:{c.source_file}:{c.build}"] = c
            recurrent.append((kind, token, list(unique.values())))

    if not recurrent:
        return RuleResult(
            rule_id=rule.id,
            name=rule.name,
            severity=rule.severity,
            status="pass",
            message=(
                f"No FA symptom/part recurrence across ≥{min_builds} builds "
                f"({len(pool)} case(s) checked)"
            ),
            details={"case_count": len(pool), "min_builds": min_builds},
        )

    citations: list[RuleCitation] = []
    details_groups: list[dict[str, Any]] = []
    for kind, token, cases in sorted(recurrent, key=lambda item: (item[0], item[1])):
        builds = sorted({c.build for c in cases})
        details_groups.append(
            {
                "match_kind": kind,
                "token": token,
                "builds": builds,
                "case_ids": [c.case_id for c in cases],
            }
        )
        for case in cases:
            citations.append(
                RuleCitation(
                    kind="case",
                    ref=case.case_id,
                    project=case.project,
                    build=case.build,
                    excerpt=(
                        f"{kind}={token!r} also in builds {', '.join(builds)}; "
                        f"source={case.source_file}"
                    ),
                )
            )
            for chunk_id in case.chunk_ids[:3]:
                citations.append(
                    RuleCitation(
                        kind="chunk",
                        ref=chunk_id,
                        project=case.project,
                        build=case.build,
                        excerpt=case.source_file,
                    )
                )

    return RuleResult(
        rule_id=rule.id,
        name=rule.name,
        severity=rule.severity,
        status="fail",
        message=(
            f"{len(recurrent)} recurring FA signal(s) across ≥{min_builds} builds"
        ),
        citations=citations,
        details={"groups": details_groups, "min_builds": min_builds},
    )
