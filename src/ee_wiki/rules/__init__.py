"""Engineering rules engine (V3 P4).

Config-driven checks evaluate the knowledge graph (and optional case index)
and return pass / fail / insufficient with citations. Generation must not
import this package to open the graph store — api / tools / CLI orchestrate.
"""

from __future__ import annotations

from ee_wiki.rules.engine import RuleEngine, open_rule_engine
from ee_wiki.rules.errors import RuleError, RulePackError
from ee_wiki.rules.loader import load_rule_pack
from ee_wiki.rules.models import (
    RuleCitation,
    RuleDefinition,
    RulePack,
    RuleResult,
    RuleStatus,
)

__all__ = [
    "RuleCitation",
    "RuleDefinition",
    "RuleEngine",
    "RuleError",
    "RulePack",
    "RulePackError",
    "RuleResult",
    "RuleStatus",
    "load_rule_pack",
    "open_rule_engine",
]
