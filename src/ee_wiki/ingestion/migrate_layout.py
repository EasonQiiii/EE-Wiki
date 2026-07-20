"""Plan and apply legacy two-level → ADR 0011 three-level raw layout moves.

Legacy trees lived at ``data/raw/{project}/...``. Canonical trees are
``data/raw/{product}/{project}/...``. This module only relocates top-level
project directories under ``data/raw/``; it never touches ``global/``,
``data/processed/``, indexes, graph, or FA cache/exports.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from ee_wiki.common.errors import MigrationError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig

logger = get_logger(__name__)


@dataclass(frozen=True)
class PlannedMove:
    """One planned relocation of a legacy project tree under a product."""

    project: str
    product: str
    source: Path
    destination: Path

    def format_line(self) -> str:
        """Return a human-readable move description."""
        return f"{self.source} → {self.destination}"


@dataclass(frozen=True)
class MigrationPlan:
    """Validated set of moves for a dry-run or apply pass."""

    moves: tuple[PlannedMove, ...]
    skipped_global: bool
    untouched_top_level: tuple[str, ...]

    @property
    def empty(self) -> bool:
        """True when no moves were planned."""
        return not self.moves


def parse_project_product_map(
    *,
    map_cli: str | None = None,
    map_file: Path | None = None,
) -> dict[str, str]:
    """Parse ``project → product`` mapping from CLI string and/or file.

    Args:
        map_cli: Comma-separated ``project=product`` pairs (e.g.
            ``logan=iphone,macon=iphone``).
        map_file: Optional YAML or JSON file. Accepted shapes:
            ``{project: product, ...}`` or ``{map: {project: product}}``.

    Returns:
        Mapping of legacy project slug → product slug.

    Raises:
        MigrationError: If neither source is provided, both conflict, or
            entries are malformed / empty.
    """
    from_cli = _parse_cli_map(map_cli) if map_cli else {}
    from_file = _parse_file_map(map_file) if map_file is not None else {}

    if not from_cli and not from_file:
        raise MigrationError(
            "Project→product mapping is required. Pass --map "
            "logan=iphone,macon=iphone and/or --map-file path.yaml"
        )

    if from_cli and from_file:
        conflicts = {
            project
            for project in from_cli
            if project in from_file and from_cli[project] != from_file[project]
        }
        if conflicts:
            raise MigrationError(
                "Conflicting product mappings for project(s): "
                + ", ".join(sorted(conflicts))
            )
        merged = {**from_file, **from_cli}
    else:
        merged = from_cli or from_file

    if not merged:
        raise MigrationError("Project→product mapping is empty")

    return merged


def _parse_cli_map(raw: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise MigrationError(
                f"Invalid --map entry '{item}'; expected project=product"
            )
        project, product = item.split("=", 1)
        project = project.strip()
        product = product.strip()
        if not project or not product:
            raise MigrationError(
                f"Invalid --map entry '{item}'; project and product must be non-empty"
            )
        if project in mapping and mapping[project] != product:
            raise MigrationError(
                f"Duplicate conflicting --map entry for project '{project}'"
            )
        mapping[project] = product
    return mapping


def _parse_file_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise MigrationError(f"Map file not found: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            loaded = json.loads(text)
        else:
            loaded = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise MigrationError(f"Failed to parse map file {path}: {exc}") from exc

    if loaded is None:
        raise MigrationError(f"Map file is empty: {path}")
    if not isinstance(loaded, dict):
        raise MigrationError(
            f"Map file must be a mapping of project→product (got {type(loaded).__name__})"
        )

    if "map" in loaded and isinstance(loaded["map"], dict) and _looks_like_slug_map(
        loaded["map"]
    ):
        raw_map = loaded["map"]
    elif _looks_like_slug_map(loaded):
        raw_map = loaded
    else:
        raise MigrationError(
            f"Map file {path} must be {{project: product, ...}} "
            "or {{map: {{project: product}}}}"
        )

    mapping: dict[str, str] = {}
    for project, product in raw_map.items():
        if not isinstance(project, str) or not isinstance(product, str):
            raise MigrationError(
                f"Map file entries must be strings (got {project!r}: {product!r})"
            )
        project = project.strip()
        product = product.strip()
        if not project or not product:
            raise MigrationError("Map file contains empty project or product slug")
        mapping[project] = product
    return mapping


def _looks_like_slug_map(value: dict[object, object]) -> bool:
    return bool(value) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


def plan_raw_layout_migration(
    raw_dir: Path,
    project_to_product: dict[str, str],
    layout: DataLayoutConfig,
) -> MigrationPlan:
    """Validate mapping and build an ordered plan of directory moves.

    Args:
        raw_dir: Absolute or relative ``data/raw`` directory.
        project_to_product: Explicit legacy project slug → product slug.
        layout: Data layout config (reserved segment names, type folders).

    Returns:
        A :class:`MigrationPlan` with zero or more :class:`PlannedMove` entries.

    Raises:
        MigrationError: On reserved names, missing sources, collisions, or
            nesting into another legacy project tree.
    """
    if not project_to_product:
        raise MigrationError("Project→product mapping is empty")

    root = raw_dir.resolve()
    if not root.is_dir():
        raise MigrationError(f"raw_dir does not exist or is not a directory: {root}")

    reserved = layout.reserved_segments
    global_seg = layout.global_segment
    type_folders = frozenset(layout.document_type_folders)

    skipped_global = (root / global_seg).is_dir()
    top_level = {
        p.name: p
        for p in sorted(root.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    }

    errors: list[str] = []
    moves: list[PlannedMove] = []
    destinations: dict[Path, str] = {}

    for project, product in sorted(project_to_product.items()):
        if project in reserved:
            errors.append(
                f"Reserved name '{project}' cannot be a legacy project slug"
            )
            continue
        if product in reserved:
            errors.append(
                f"Reserved name '{product}' cannot be used as a product slug "
                f"(project '{project}')"
            )
            continue

        source = top_level.get(project)
        if source is None:
            errors.append(
                f"Legacy project '{project}' not found under {root} "
                f"(expected directory {root / project})"
            )
            continue

        if project == global_seg:
            errors.append(f"Refusing to move enterprise library '{global_seg}/'")
            continue

        destination = root / product / project
        if destination.exists():
            errors.append(
                f"Collision: destination already exists for '{project}': {destination}"
            )
            continue

        try:
            destination.resolve().relative_to(source.resolve())
        except ValueError:
            pass
        else:
            errors.append(
                f"Refusing to move '{project}' into itself "
                f"({source} → {destination}); choose a different product slug"
            )
            continue

        if destination in destinations:
            errors.append(
                f"Collision: two projects resolve to the same destination "
                f"{destination} ('{destinations[destination]}' and '{project}')"
            )
            continue

        parent = root / product
        nest_error = _unsafe_product_parent(
            parent=parent,
            product=product,
            project=project,
            project_to_product=project_to_product,
            top_level=top_level,
            type_folders=type_folders,
            reserved=reserved,
            global_seg=global_seg,
        )
        if nest_error:
            errors.append(nest_error)
            continue

        destinations[destination] = project
        moves.append(
            PlannedMove(
                project=project,
                product=product,
                source=source,
                destination=destination,
            )
        )

    if errors:
        raise MigrationError(
            "Unsafe or invalid migration plan:\n- " + "\n- ".join(errors)
        )

    mapped = set(project_to_product)
    untouched = tuple(
        sorted(
            name
            for name in top_level
            if name != global_seg and name not in mapped and name not in {
                move.product for move in moves
            }
        )
    )

    return MigrationPlan(
        moves=tuple(moves),
        skipped_global=skipped_global,
        untouched_top_level=untouched,
    )


def _unsafe_product_parent(
    *,
    parent: Path,
    product: str,
    project: str,
    project_to_product: dict[str, str],
    top_level: dict[str, Path],
    type_folders: frozenset[str],
    reserved: frozenset[str],
    global_seg: str,
) -> str | None:
    """Return an error message if nesting under ``product`` would be unsafe."""
    if product in project_to_product:
        return (
            f"Product '{product}' is also a mapped legacy project; "
            f"refusing to nest '{project}' under a tree that will move "
            f"(or currently is a legacy project root)"
        )

    if product not in top_level:
        return None

    existing = top_level[product]
    if product == global_seg:
        return f"Refusing to use reserved '{global_seg}' as a product parent"

    # Immediate type folders under product ⇒ legacy / malformed tree
    child_names = {
        p.name for p in existing.iterdir() if p.is_dir() and not p.name.startswith(".")
    }
    type_hits = sorted(child_names & type_folders)
    if type_hits:
        return (
            f"Product parent '{existing}' looks like a document tree "
            f"(type folders {type_hits}), not a product container; "
            f"refusing to nest '{project}' there"
        )

    # Legacy two-level project: children are builds / common with type folders
    if _looks_like_legacy_project_root(existing, type_folders, reserved):
        return (
            f"Product parent '{existing}' looks like a legacy two-level project "
            f"root; refusing to nest '{project}' inside it. Map that project "
            f"first or choose a different product slug."
        )

    return None


def _looks_like_legacy_project_root(
    path: Path,
    type_folders: frozenset[str],
    reserved: frozenset[str],
) -> bool:
    """Heuristic: top-level dir whose children look like builds, not projects."""
    children = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not children:
        return False

    build_like = 0
    project_like = 0
    for child in children:
        grand = {
            p.name
            for p in child.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        }
        if grand & type_folders:
            # child/common/note or child/p1/sch → legacy build or project-common
            build_like += 1
        elif any(
            (child / g).is_dir()
            and {
                x.name
                for x in (child / g).iterdir()
                if x.is_dir() and not x.name.startswith(".")
            }
            & type_folders
            for g in grand
        ):
            # child/project/build/type → already a product container
            project_like += 1
        elif child.name in reserved:
            # product/common without inspecting deeper still OK for product
            project_like += 1

    return build_like > 0 and project_like == 0


def apply_raw_layout_migration(plan: MigrationPlan) -> list[PlannedMove]:
    """Execute planned moves with ``shutil.move``.

    Args:
        plan: Previously validated migration plan.

    Returns:
        The list of moves that were applied.

    Raises:
        MigrationError: If the plan is empty or a move fails mid-flight.
    """
    if plan.empty:
        raise MigrationError("Nothing to apply: migration plan has no moves")

    applied: list[PlannedMove] = []
    for move in plan.moves:
        if not move.source.is_dir():
            raise MigrationError(
                f"Source disappeared before apply: {move.source} "
                f"(already applied: {[m.project for m in applied]})"
            )
        if move.destination.exists():
            raise MigrationError(
                f"Destination appeared before apply: {move.destination}"
            )
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Moving %s → %s", move.source, move.destination)
        try:
            shutil.move(str(move.source), str(move.destination))
        except OSError as exc:
            raise MigrationError(
                f"Failed to move {move.source} → {move.destination}: {exc}. "
                f"Already applied: {[m.project for m in applied]}"
            ) from exc
        applied.append(move)
    return applied


def format_plan_report(plan: MigrationPlan, *, apply: bool) -> str:
    """Render a dry-run or apply summary for stdout."""
    mode = "APPLY" if apply else "DRY-RUN"
    lines = [f"[{mode}] Planned moves: {len(plan.moves)}"]
    if plan.skipped_global:
        lines.append("Leaving data/raw/global/ untouched")
    for move in plan.moves:
        lines.append(f"  {move.format_line()}")
    if plan.untouched_top_level:
        lines.append(
            "Untouched top-level directories (not in map): "
            + ", ".join(plan.untouched_top_level)
        )
    if not apply:
        lines.append("No files were moved. Re-run with --apply to execute.")
    else:
        lines.append(
            "Raw moves complete. Do NOT move processed/indexes/graph — "
            "delete/recreate them, then ingest → index → build_graph. "
            "FA cache/exports stay Radar-keyed and were not moved."
        )
    return "\n".join(lines)
