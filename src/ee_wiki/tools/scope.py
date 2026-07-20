"""Scope envelope for ToolBus calls (ADR 0008 §5).

The supervisor attaches a :class:`ScopeEnvelope` to every tool call. Specialists
cannot widen ``product`` / ``project`` / ``build`` beyond the envelope; ToolBus
clamps incoming args before invoking handlers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeEnvelope:
    """Immutable product/project/build envelope for one agent turn.

    Attributes:
        product: Locked product slug (or ``None`` for unscoped reads).
        project: Locked project slug (or ``None`` for unscoped reads).
        build: Locked build slug (or ``None``).
        scope_inheritance: Whether handlers may expand to common/global.
    """

    product: str | None = None
    project: str | None = None
    build: str | None = None
    scope_inheritance: bool = True

    def clamp_args(self, args: dict) -> dict:
        """Return a copy of ``args`` with product/project/build clamped.

        Args:
            args: Caller-supplied tool arguments.

        Returns:
            New dict where ``product`` / ``project`` / ``build`` cannot exceed
            the envelope. When the envelope sets a field, caller values that
            differ are overwritten; when the envelope leaves a field ``None``,
            the caller value is kept (after optional inheritance flag injection).
        """
        out = dict(args)
        if self.product is not None:
            out["product"] = self.product
        if self.project is not None:
            out["project"] = self.project
        if self.build is not None:
            out["build"] = self.build
        out.setdefault("scope_inheritance", self.scope_inheritance)
        return out
