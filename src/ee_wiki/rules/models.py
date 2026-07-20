"""Rule definition and evaluation result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RuleStatus = Literal["pass", "fail", "insufficient"]
RuleSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class RuleCitation:
    """Provenance for a rule finding (graph node, case, document, or chunk)."""

    kind: str
    ref: str
    product: str = ""
    project: str = ""
    build: str = ""
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / MCP payloads."""
        payload: dict[str, Any] = {
            "kind": self.kind,
            "ref": self.ref,
        }
        if self.product:
            payload["product"] = self.product
        if self.project:
            payload["project"] = self.project
        if self.build:
            payload["build"] = self.build
        if self.excerpt:
            payload["excerpt"] = self.excerpt
        return payload


@dataclass(frozen=True)
class RuleDefinition:
    """One config-driven engineering rule."""

    id: str
    name: str
    description: str
    check_type: str
    severity: RuleSeverity = "warning"
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize rule metadata (no evaluation)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "check_type": self.check_type,
            "severity": self.severity,
            "enabled": self.enabled,
            "params": dict(self.params),
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class RulePack:
    """Loaded collection of rule definitions."""

    pack_dir: str
    rules: tuple[RuleDefinition, ...] = ()

    def by_id(self) -> dict[str, RuleDefinition]:
        """Return rules keyed by id (last wins on duplicate ids)."""
        return {rule.id: rule for rule in self.rules}

    def enabled_rules(self) -> list[RuleDefinition]:
        """Return enabled rules in pack order."""
        return [rule for rule in self.rules if rule.enabled]


@dataclass
class RuleResult:
    """Outcome of evaluating one rule in a given scope."""

    rule_id: str
    status: RuleStatus
    message: str
    severity: RuleSeverity = "warning"
    name: str = ""
    citations: list[RuleCitation] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / MCP payloads."""
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "citations": [c.to_dict() for c in self.citations],
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload
