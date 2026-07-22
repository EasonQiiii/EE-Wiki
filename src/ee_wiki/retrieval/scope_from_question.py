"""Infer product/project/build from natural-language chat questions.

Open WebUI and most chat clients do **not** send ``body.product`` /
``body.project`` / ``body.build``. Scope must be recovered from the question
text (e.g. ``logan p1 原理图 …``) before Supervisor / FaAgent / tools run —
otherwise ``trace_net`` and FA unbound sessions see ``none/none/none``.
"""

from __future__ import annotations

import re
from typing import Any

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.project_aliases import canonicalize_scope_filters

logger = get_logger(__name__)

_BUILD_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(p\d+|evt\d*|dvt\d*|pvt|mp)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def infer_scope_from_aliases(
    question: str,
    config: AppConfig,
) -> tuple[str | None, str | None, str | None]:
    """Parse ``logan p1``-style tokens using ``project_aliases`` (no index).

    Prefers alias targets shaped as ``product/project`` (e.g. ``ipad/logan``)
    over bare project slugs so chat tools get a complete filter.
    """
    aliases = getattr(config.data_layout, "project_aliases", None) or {}
    product: str | None = None
    project: str | None = None
    build: str | None = None

    build_match = _BUILD_TOKEN.search(question)
    if build_match:
        build = build_match.group(1).lower()

    for alias, target in sorted(
        ((str(k), str(v)) for k, v in aliases.items()),
        key=lambda item: -len(item[0]),
    ):
        if not re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
            question,
            re.IGNORECASE,
        ):
            continue
        if "/" in target:
            product, project = target.split("/", 1)
        else:
            project = target
        break

    if project is None:
        candidates: list[tuple[str | None, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in aliases.values():
            t = str(target)
            if "/" in t:
                cand_product, cand_project = t.split("/", 1)
            else:
                cand_product, cand_project = None, t
            key = (cand_product or "", cand_project.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append((cand_product, cand_project))
        candidates.sort(key=lambda item: (0 if item[0] else 1, -len(item[1])))
        for cand_product, cand_project in candidates:
            if not re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(cand_project)}(?![A-Za-z0-9_])",
                question,
                re.IGNORECASE,
            ):
                continue
            project = cand_project
            if cand_product:
                product = cand_product
            break

    return product, project, build


def infer_scope_from_catalog(
    question: str,
    config: AppConfig,
    engine: Any | None,
) -> tuple[str | None, str | None, str | None]:
    """Use index-backed scope catalog extraction when available."""
    if engine is None or not hasattr(engine, "get_scope_catalog"):
        return None, None, None
    gen = getattr(config, "generation", None)
    if gen is not None and not getattr(gen, "scope_inference", True):
        return None, None, None
    try:
        from ee_wiki.retrieval.scope_extract import extract_scope_rules
        from ee_wiki.retrieval.scope_resolve import resolve_retrieval_targets

        catalog = engine.get_scope_catalog()
    except Exception:  # noqa: BLE001 — inference is best-effort
        logger.debug("Catalog scope inference unavailable", exc_info=True)
        return None, None, None
    if catalog is None:
        return None, None, None
    inferred = extract_scope_rules(question, catalog)
    if inferred is None:
        return None, None, None
    targets = resolve_retrieval_targets(inferred, catalog, config.data_layout)
    return targets[0], targets[1], targets[2]


def merge_scope_from_question(
    question: str,
    *,
    config: AppConfig,
    engine: Any | None = None,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Fill missing scope axes from the question text.

    Order: keep explicit API/body values → catalog rules → alias/build tokens →
    canonicalize through ``project_aliases``.
    """
    if product and project and build:
        return canonicalize_scope_filters(
            product,
            project,
            build,
            aliases=config.data_layout.project_aliases,
            require_product=False,
        )

    c_product, c_project, c_build = infer_scope_from_catalog(
        question, config, engine
    )
    product = product or c_product
    project = project or c_project
    build = build or c_build

    if not (product and project and build):
        a_product, a_project, a_build = infer_scope_from_aliases(question, config)
        product = product or a_product
        project = project or a_project
        build = build or a_build

    if product or project or build:
        logger.info(
            "Chat scope from question product=%s project=%s build=%s",
            product,
            project,
            build,
        )
    return canonicalize_scope_filters(
        product,
        project,
        build,
        aliases=config.data_layout.project_aliases,
        require_product=False,
    )
