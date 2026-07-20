"""Stable node id helpers for the knowledge graph.

Scoped ids embed the full ``{product}/{project}/{build}`` triple so identical
project or build slugs under two different products can never collide
(ADR 0011).
"""

from __future__ import annotations


def _norm(token: str) -> str:
    return token.strip().upper()


def _scope_path(product: str, project: str, build: str) -> str:
    return f"{product.strip()}/{project.strip()}/{build.strip()}"


def product_node_id(product: str) -> str:
    """Return the node id for a product scope node."""
    return f"product:{product.strip()}"


def project_node_id(product: str, project: str) -> str:
    """Return the node id for a project scope node."""
    return f"project:{product.strip()}/{project.strip()}"


def build_node_id(product: str, project: str, build: str) -> str:
    """Return the node id for a build scope node."""
    return f"build:{_scope_path(product, project, build)}"


def document_node_id(product: str, project: str, build: str, source_file: str) -> str:
    """Return the node id for a document node."""
    return f"document:{_scope_path(product, project, build)}:{source_file.strip()}"


def component_node_id(product: str, project: str, build: str, designator: str) -> str:
    """Return the node id for a scoped schematic designator."""
    return f"component:{_scope_path(product, project, build)}:{_norm(designator)}"


def part_node_id(part_number: str) -> str:
    """Return the node id for a part-number identity (cross-scope)."""
    return f"part:{_norm(part_number)}"


def net_node_id(product: str, project: str, build: str, net_name: str) -> str:
    """Return the node id for a scoped net."""
    return f"net:{_scope_path(product, project, build)}:{_norm(net_name)}"


def case_node_id(product: str, project: str, build: str, case_id: str) -> str:
    """Return the node id for a scoped debug / FA case."""
    return f"case:{_scope_path(product, project, build)}:{_norm(case_id)}"


def rail_node_id(product: str, project: str, build: str, rail_name: str) -> str:
    """Return the node id for a scoped power rail."""
    return f"rail:{_scope_path(product, project, build)}:{_norm(rail_name)}"
