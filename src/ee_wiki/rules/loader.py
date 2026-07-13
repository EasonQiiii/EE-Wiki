"""Load engineering rule packs from YAML files under ``config/rules/``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ee_wiki.common.logging import get_logger
from ee_wiki.rules.errors import RulePackError
from ee_wiki.rules.models import RuleDefinition, RulePack, RuleSeverity

logger = get_logger(__name__)

_VALID_SEVERITIES: set[str] = {"error", "warning", "info"}


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_rule(data: dict[str, Any], *, source_path: str) -> RuleDefinition:
    rule_id = _as_str(data.get("id"))
    if not rule_id:
        raise RulePackError(f"Rule missing id in {source_path}")

    check = data.get("check")
    if not isinstance(check, dict):
        raise RulePackError(f"Rule {rule_id!r} missing check mapping in {source_path}")

    check_type = _as_str(check.get("type"))
    if not check_type:
        raise RulePackError(f"Rule {rule_id!r} missing check.type in {source_path}")

    params = check.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RulePackError(f"Rule {rule_id!r} check.params must be a mapping in {source_path}")

    severity_raw = _as_str(data.get("severity"), "warning").lower()
    if severity_raw not in _VALID_SEVERITIES:
        raise RulePackError(
            f"Rule {rule_id!r} has invalid severity {severity_raw!r} in {source_path}"
        )
    severity: RuleSeverity = severity_raw  # type: ignore[assignment]

    return RuleDefinition(
        id=rule_id,
        name=_as_str(data.get("name"), rule_id),
        description=_as_str(data.get("description")),
        check_type=check_type,
        severity=severity,
        enabled=bool(data.get("enabled", True)),
        params=dict(params),
        source_path=source_path,
    )


def load_rule_pack(pack_dir: Path) -> RulePack:
    """Load all ``*.yaml`` / ``*.yml`` rule files from ``pack_dir``.

    Args:
        pack_dir: Directory containing rule YAML files.

    Returns:
        :class:`RulePack` with rules sorted by id.

    Raises:
        RulePackError: If the directory is missing or a file is invalid.
    """
    root = pack_dir.resolve()
    if not root.is_dir():
        raise RulePackError(f"Rule pack directory not found: {root}")

    rules: list[RuleDefinition] = []
    paths = sorted(
        [*root.glob("*.yaml"), *root.glob("*.yml")],
        key=lambda p: p.name.lower(),
    )
    if not paths:
        logger.warning("No rule YAML files found under %s", root)

    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RulePackError(f"Failed to read rule file {path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise RulePackError(f"Invalid YAML in {path}: {exc}") from exc

        if raw is None:
            logger.warning("Skipping empty rule file %s", path)
            continue
        if not isinstance(raw, dict):
            raise RulePackError(f"Rule file must be a mapping: {path}")

        rule = _parse_rule(raw, source_path=str(path))
        rules.append(rule)
        logger.debug("Loaded rule %s from %s", rule.id, path.name)

    # Stable order by id; warn on duplicates
    by_id: dict[str, RuleDefinition] = {}
    for rule in rules:
        if rule.id in by_id:
            logger.warning(
                "Duplicate rule id %s (%s overrides %s)",
                rule.id,
                rule.source_path,
                by_id[rule.id].source_path,
            )
        by_id[rule.id] = rule

    ordered = tuple(sorted(by_id.values(), key=lambda r: r.id))
    return RulePack(pack_dir=str(root), rules=ordered)
