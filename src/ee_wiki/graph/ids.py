"""Stable node id helpers for the knowledge graph."""

from __future__ import annotations


def _norm(token: str) -> str:
    return token.strip().upper()


def project_node_id(project: str) -> str:
    """Return the node id for a project scope node."""
    return f"project:{project.strip()}"


def build_node_id(project: str, build: str) -> str:
    """Return the node id for a build scope node."""
    return f"build:{project.strip()}/{build.strip()}"


def document_node_id(project: str, build: str, source_file: str) -> str:
    """Return the node id for a document node."""
    return f"document:{project.strip()}/{build.strip()}:{source_file.strip()}"


def component_node_id(project: str, build: str, designator: str) -> str:
    """Return the node id for a scoped schematic designator."""
    return f"component:{project.strip()}/{build.strip()}:{_norm(designator)}"


def part_node_id(part_number: str) -> str:
    """Return the node id for a part-number identity (cross-scope)."""
    return f"part:{_norm(part_number)}"


def net_node_id(project: str, build: str, net_name: str) -> str:
    """Return the node id for a scoped net."""
    return f"net:{project.strip()}/{build.strip()}:{_norm(net_name)}"


def case_node_id(project: str, build: str, case_id: str) -> str:
    """Return the node id for a scoped debug / FA case."""
    return f"case:{project.strip()}/{build.strip()}:{_norm(case_id)}"


def rail_node_id(project: str, build: str, rail_name: str) -> str:
    """Return the node id for a scoped power rail."""
    return f"rail:{project.strip()}/{build.strip()}:{_norm(rail_name)}"
