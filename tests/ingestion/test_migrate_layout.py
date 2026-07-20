"""Tests for legacy → ADR 0011 raw layout migration planning and apply."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ee_wiki.common.errors import MigrationError
from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.migrate_layout import (
    apply_raw_layout_migration,
    parse_project_product_map,
    plan_raw_layout_migration,
)


@pytest.fixture
def layout(tmp_path: Path) -> DataLayoutConfig:
    """Minimal data layout pointing at a temp raw dir."""
    raw = tmp_path / "raw"
    raw.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={
            "note": "engineering_note",
            "sch": "schematic",
            "sop": "sop",
            "datasheet": "datasheet",
            "fa": "failure_analysis",
        },
        raw_dir=raw,
        processed_dir=processed,
    )


def _touch_tree(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


class TestParseMap:
    def test_cli_map(self) -> None:
        assert parse_project_product_map(map_cli="logan=iphone,macon=iphone") == {
            "logan": "iphone",
            "macon": "iphone",
        }

    def test_yaml_map_file(self, tmp_path: Path) -> None:
        path = tmp_path / "map.yaml"
        path.write_text(yaml.dump({"logan": "iphone", "macon": "iphone"}), encoding="utf-8")
        assert parse_project_product_map(map_file=path) == {
            "logan": "iphone",
            "macon": "iphone",
        }

    def test_requires_mapping(self) -> None:
        with pytest.raises(MigrationError, match="required"):
            parse_project_product_map()


class TestPlanDryRun:
    def test_plans_moves_leaves_global(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "global/note/shared.md")
        _touch_tree(raw, "logan/p1/sch/board.pdf")
        _touch_tree(raw, "logan/common/sop/bringup.md")
        _touch_tree(raw, "macon/p1/note/x.md")

        plan = plan_raw_layout_migration(
            raw,
            {"logan": "iphone", "macon": "iphone"},
            layout,
        )

        assert plan.skipped_global is True
        assert len(plan.moves) == 2
        by_project = {m.project: m for m in plan.moves}
        assert by_project["logan"].destination == raw / "iphone" / "logan"
        assert by_project["macon"].destination == raw / "iphone" / "macon"
        # Dry-run must not move anything
        assert (raw / "logan" / "p1" / "sch" / "board.pdf").is_file()
        assert (raw / "global" / "note" / "shared.md").is_file()
        assert not (raw / "iphone").exists()

    def test_apply_moves_and_leaves_global(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "global/note/shared.md")
        _touch_tree(raw, "logan/p1/sch/board.pdf")
        _touch_tree(raw, "logan/common/sop/bringup.md")

        plan = plan_raw_layout_migration(raw, {"logan": "iphone"}, layout)
        applied = apply_raw_layout_migration(plan)

        assert len(applied) == 1
        assert not (raw / "logan").exists()
        assert (raw / "iphone" / "logan" / "p1" / "sch" / "board.pdf").is_file()
        assert (raw / "iphone" / "logan" / "common" / "sop" / "bringup.md").is_file()
        assert (raw / "global" / "note" / "shared.md").is_file()


class TestCollisionsAndReserved:
    def test_collision_destination_exists(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "logan/p1/sch/a.pdf")
        _touch_tree(raw, "iphone/logan/p1/sch/existing.pdf")

        with pytest.raises(MigrationError, match="Collision"):
            plan_raw_layout_migration(raw, {"logan": "iphone"}, layout)

    def test_rejects_reserved_project(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "global/note/x.md")

        with pytest.raises(MigrationError, match="Reserved name 'global'"):
            plan_raw_layout_migration(raw, {"global": "iphone"}, layout)

    def test_rejects_reserved_product(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "logan/p1/sch/a.pdf")

        with pytest.raises(MigrationError, match="Reserved name 'common'"):
            plan_raw_layout_migration(raw, {"logan": "common"}, layout)

    def test_rejects_nesting_into_legacy_sibling(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "logan/p1/sch/a.pdf")
        _touch_tree(raw, "macon/p1/sch/b.pdf")

        with pytest.raises(MigrationError, match="legacy two-level"):
            plan_raw_layout_migration(raw, {"logan": "macon"}, layout)

    def test_rejects_product_that_is_also_mapped_source(
        self, layout: DataLayoutConfig
    ) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "logan/p1/sch/a.pdf")
        _touch_tree(raw, "macon/p1/sch/b.pdf")

        with pytest.raises(MigrationError, match="also a mapped legacy project"):
            plan_raw_layout_migration(
                raw,
                {"logan": "macon", "macon": "iphone"},
                layout,
            )

    def test_rejects_self_nesting(self, layout: DataLayoutConfig) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "logan/p1/sch/a.pdf")

        with pytest.raises(MigrationError, match="into itself"):
            plan_raw_layout_migration(raw, {"logan": "logan"}, layout)

    def test_allows_nesting_under_existing_product(
        self, layout: DataLayoutConfig
    ) -> None:
        raw = layout.raw_dir
        _touch_tree(raw, "iphone/macon/p1/sch/b.pdf")
        _touch_tree(raw, "logan/p1/sch/a.pdf")

        plan = plan_raw_layout_migration(raw, {"logan": "iphone"}, layout)
        assert len(plan.moves) == 1
        apply_raw_layout_migration(plan)
        assert (raw / "iphone" / "logan" / "p1" / "sch" / "a.pdf").is_file()
        assert (raw / "iphone" / "macon" / "p1" / "sch" / "b.pdf").is_file()

    def test_missing_source(self, layout: DataLayoutConfig) -> None:
        with pytest.raises(MigrationError, match="not found"):
            plan_raw_layout_migration(layout.raw_dir, {"logan": "iphone"}, layout)
