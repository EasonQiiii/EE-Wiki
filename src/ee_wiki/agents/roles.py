"""Load and validate agent role packs (ADR 0008)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ee_wiki.common.errors import ConfigError
from ee_wiki.tools.bus import BANNED_TOOLS, REGISTERED_TOOLS

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RecipeStep:
    """One tool invocation step in a role recipe."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    query_from: str | None = None  # question | tokens | None


@dataclass(frozen=True)
class RolePack:
    """Validated specialist role configuration."""

    id: str
    display_name: str
    keywords: tuple[str, ...]
    tools: frozenset[str]
    recipe: tuple[RecipeStep, ...]
    max_tool_calls: int = 4


def _schema_path(roles_dir: Path) -> Path:
    # config/agents/roles → config/schema/agents_role.schema.json
    return roles_dir.parent.parent / "schema" / "agents_role.schema.json"


def load_role_pack(path: Path, *, schema: dict | None = None) -> RolePack:
    """Load and validate one role YAML file.

    Args:
        path: Path to ``*.yaml`` role pack.
        schema: Optional pre-loaded JSON schema dict.

    Returns:
        Validated :class:`RolePack`.

    Raises:
        ConfigError: On parse/schema/tool-allowlist failures.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Failed to load role pack {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Role pack root must be a mapping: {path}")

    if schema is not None and jsonschema is not None:
        try:
            jsonschema.validate(raw, schema)
        except jsonschema.ValidationError as exc:
            raise ConfigError(f"Role pack schema invalid ({path}): {exc.message}") from exc

    tools = [str(t) for t in (raw.get("tools") or [])]
    for tool in tools:
        if tool in BANNED_TOOLS:
            raise ConfigError(f"Role {raw.get('id')!r} lists banned tool {tool!r}")
        if tool not in REGISTERED_TOOLS:
            raise ConfigError(
                f"Role {raw.get('id')!r} lists unknown tool {tool!r}; "
                f"registered={sorted(REGISTERED_TOOLS)}"
            )

    recipe_raw = raw.get("recipe") or []
    recipe: list[RecipeStep] = []
    for step in recipe_raw:
        tool = str(step["tool"])
        if tool not in tools:
            raise ConfigError(
                f"Role {raw.get('id')!r} recipe uses tool {tool!r} "
                f"not in its allowlist {tools}"
            )
        recipe.append(
            RecipeStep(
                tool=tool,
                args=dict(step.get("args") or {}),
                query_from=step.get("query_from"),
            )
        )

    routing = raw.get("routing") or {}
    keywords = tuple(str(k) for k in (routing.get("keywords") or []))
    if not keywords:
        raise ConfigError(f"Role {raw.get('id')!r} needs routing.keywords")

    return RolePack(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        keywords=keywords,
        tools=frozenset(tools),
        recipe=tuple(recipe),
        max_tool_calls=int(raw.get("max_tool_calls", 4)),
    )


def load_all_roles(roles_dir: Path) -> dict[str, RolePack]:
    """Load every ``*.yaml`` role pack under ``roles_dir``.

    Args:
        roles_dir: Directory containing role YAML files.

    Returns:
        Map of role id → pack.

    Raises:
        ConfigError: If directory missing, empty, or any pack invalid.
    """
    if not roles_dir.is_dir():
        raise ConfigError(f"Agent roles directory not found: {roles_dir}")

    schema: dict | None = None
    schema_file = _schema_path(roles_dir)
    if schema_file.is_file():
        schema = json.loads(schema_file.read_text(encoding="utf-8"))

    packs: dict[str, RolePack] = {}
    for path in sorted(roles_dir.glob("*.yaml")):
        pack = load_role_pack(path, schema=schema)
        if pack.id in packs:
            raise ConfigError(f"Duplicate role id {pack.id!r}")
        packs[pack.id] = pack

    if not packs:
        raise ConfigError(f"No role packs found under {roles_dir}")
    if "hw" not in packs:
        raise ConfigError("Role pack 'hw' is required as the default fallback specialist")
    return packs
