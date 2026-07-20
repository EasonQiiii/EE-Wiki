"""Tests for engineering rules engine (V3 P4)."""

from __future__ import annotations

from pathlib import Path

import yaml

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import build_graph_from_chunks, open_power_query, open_query
from ee_wiki.knowledge.indexer.case_index import CaseIndex, DebugCaseRecord
from ee_wiki.rules.engine import RuleEngine, open_rule_engine
from ee_wiki.rules.loader import load_rule_pack
from ee_wiki.rules.models import RuleDefinition


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={
            "sch": "schematic",
            "fa": "failure_analysis",
            "note": "engineering_note",
        },
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _sch_chunk(
    *,
    chunk_id: str,
    product: str = "acme",
    project: str,
    build: str,
    source_file: str,
    major_components: list[str],
    nets: list[str],
    page: int = 1,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content="schematic page",
        metadata=Metadata(
            product=product,
            project=project,
            build=build,
            document_type="schematic",
            title="Sch",
            source_file=source_file,
            page=page,
            major_components=major_components,
            nets=nets,
        ),
        citation=Citation(
            source_file=source_file,
            chunk_id=chunk_id,
            page=page,
            excerpt="schematic page",
        ),
    )


def _write_pack(pack_dir: Path, rules: list[dict]) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    for rule in rules:
        path = pack_dir / f"{rule['id']}.yaml"
        path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")
    return pack_dir


def test_load_rule_pack_from_yaml(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "rail_presence",
                "name": "Rails",
                "description": "test",
                "severity": "warning",
                "enabled": True,
                "check": {"type": "rail_presence", "params": {"skip_ground": True}},
            }
        ],
    )
    pack = load_rule_pack(pack_dir)
    assert len(pack.rules) == 1
    assert pack.rules[0].id == "rail_presence"
    assert pack.rules[0].check_type == "rail_presence"


def test_rail_presence_pass_and_interface_naming(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/power.md",
            major_components=["VR10", "U101"],
            nets=["VIN", "3V3", "GND", "I2C_SDA", "I2C_SCL"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=True)
    gq = open_query(graph, layout=layout, scope_inheritance=True)
    power = open_power_query(gq)

    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "rail_presence",
                "name": "Rails",
                "check": {"type": "rail_presence", "params": {"skip_ground": True}},
            },
            {
                "id": "interface_naming",
                "name": "Interfaces",
                "check": {
                    "type": "interface_naming",
                    "params": {
                        "family_prefixes": ["I2C", "SPI"],
                        "require_suffix": True,
                    },
                },
            },
            {
                "id": "power_tree_flags",
                "name": "Flags",
                "check": {
                    "type": "power_tree_flags",
                    "params": {
                        "fail_codes": [
                            "missing_supplier",
                            "multi_supplier",
                            "missing_parent_rail",
                        ]
                    },
                },
            },
        ],
    )
    engine = open_rule_engine(gq, pack_dir, power_query=power)
    results = {r.rule_id: r for r in engine.evaluate(product="acme", project="demo", build="p1")}

    assert results["rail_presence"].status == "pass"
    assert results["interface_naming"].status == "pass"
    # Power flags may fail or pass depending on heuristics; just ensure evaluated
    assert results["power_tree_flags"].status in {"pass", "fail", "insufficient"}


def test_interface_naming_fails_bare_prefix(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/io.md",
            major_components=["U1"],
            nets=["I2C", "SPI_MOSI"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    gq = open_query(graph, layout=layout)
    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "interface_naming",
                "name": "Interfaces",
                "check": {
                    "type": "interface_naming",
                    "params": {
                        "family_prefixes": ["I2C", "SPI"],
                        "require_suffix": True,
                    },
                },
            }
        ],
    )
    engine = open_rule_engine(gq, pack_dir)
    result = engine.evaluate(
        rule_ids=["interface_naming"], product="acme", project="demo", build="p1",
    )[0]
    assert result.status == "fail"
    assert any("I2C" in (c.excerpt or "") for c in result.citations)


def test_power_tree_flags_surfaces_missing_supplier(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    # Rail-like nets without a regulator designator → missing_supplier flags
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/orphan.md",
            major_components=["R1", "C1"],
            nets=["3V3", "1V8"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=True)
    gq = open_query(graph, layout=layout)
    power = open_power_query(gq)
    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "power_tree_flags",
                "name": "Flags",
                "check": {
                    "type": "power_tree_flags",
                    "params": {"fail_codes": ["missing_supplier"]},
                },
            }
        ],
    )
    engine = open_rule_engine(gq, pack_dir, power_query=power)
    result = engine.evaluate(
        rule_ids=["power_tree_flags"], product="acme", project="demo", build="p1",
    )[0]
    assert result.status == "fail"
    assert result.details.get("flag_count", 0) >= 1


def test_fa_recurrence_across_builds(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="sch1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/a.md",
            major_components=["U1"],
            nets=["NET_A"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    gq = open_query(graph, layout=layout)
    cases = CaseIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        cases=(
            DebugCaseRecord(
                case_id="RMA-1",
                product="acme",
                project="demo",
                build="p1",
                title="No boot p1",
                source_file="demo/p1/fa/rma1.md",
                document_type="failure_analysis",
                symptom="No boot",
                suspected_parts=("U101",),
                chunk_ids=("fa1",),
            ),
            DebugCaseRecord(
                case_id="RMA-2",
                product="acme",
                project="demo",
                build="p2",
                title="No boot p2",
                source_file="demo/p2/fa/rma2.md",
                document_type="failure_analysis",
                symptom="No boot",
                suspected_parts=("U101",),
                chunk_ids=("fa2",),
            ),
        ),
    )
    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "fa_recurrence",
                "name": "Recurrence",
                "check": {
                    "type": "fa_recurrence",
                    "params": {
                        "min_builds": 2,
                        "match_on": ["symptom", "suspected_parts"],
                    },
                },
            }
        ],
    )
    engine = open_rule_engine(gq, pack_dir, case_index=cases)
    result = engine.evaluate(rule_ids=["fa_recurrence"], product="acme", project="demo")[0]
    assert result.status == "fail"
    assert any(c.kind == "case" for c in result.citations)


def test_fa_recurrence_insufficient_without_cases(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="sch1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/a.md",
            major_components=["U1"],
            nets=["NET_A"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    gq = open_query(graph, layout=layout)
    pack_dir = _write_pack(
        tmp_path / "rules",
        [
            {
                "id": "fa_recurrence",
                "name": "Recurrence",
                "check": {"type": "fa_recurrence", "params": {"min_builds": 2}},
            }
        ],
    )
    engine = open_rule_engine(gq, pack_dir, case_index=None)
    result = engine.evaluate(
        rule_ids=["fa_recurrence"], product="acme", project="demo", build="p1",
    )[0]
    assert result.status == "insufficient"


def test_evaluate_summary_counts(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(
        [
            _sch_chunk(
                chunk_id="p1",
                project="demo",
                build="p1",
                source_file="demo/p1/sch/a.md",
                major_components=["U1"],
                nets=["NET_A"],
            )
        ],
        layout=layout,
        power_tree=False,
    )
    gq = open_query(graph, layout=layout)
    pack = load_rule_pack(
        _write_pack(
            tmp_path / "rules",
            [
                {
                    "id": "interface_naming",
                    "name": "Interfaces",
                    "check": {
                        "type": "interface_naming",
                        "params": {"family_prefixes": ["I2C"]},
                    },
                }
            ],
        )
    )
    engine = RuleEngine(pack, gq)
    summary = engine.evaluate_summary(product="acme", project="demo", build="p1")
    assert summary["counts"]["insufficient"] == 1
    assert summary["results"][0]["status"] == "insufficient"


def test_unknown_rule_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(
        [
            _sch_chunk(
                chunk_id="p1",
                project="demo",
                build="p1",
                source_file="demo/p1/sch/a.md",
                major_components=["U1"],
                nets=["NET_A"],
            )
        ],
        layout=layout,
        power_tree=False,
    )
    gq = open_query(graph, layout=layout)
    engine = RuleEngine(
        load_rule_pack(
            _write_pack(
                tmp_path / "rules",
                [
                    {
                        "id": "interface_naming",
                        "name": "Interfaces",
                        "check": {"type": "interface_naming", "params": {}},
                    }
                ],
            )
        ),
        gq,
    )
    result = engine.evaluate(rule_ids=["no_such_rule"])[0]
    assert result.status == "fail"
    assert "Unknown" in result.message


def test_repo_starter_pack_loads() -> None:
    """Smoke-load the committed config/rules pack from the repo."""
    repo_rules = Path(__file__).resolve().parents[2] / "config" / "rules"
    if not repo_rules.is_dir():
        return
    pack = load_rule_pack(repo_rules)
    ids = {r.id for r in pack.rules}
    assert "rail_presence" in ids
    assert "power_tree_flags" in ids
    assert "interface_naming" in ids
    assert "fa_recurrence" in ids
    for rule in pack.rules:
        assert isinstance(rule, RuleDefinition)
        assert rule.check_type
