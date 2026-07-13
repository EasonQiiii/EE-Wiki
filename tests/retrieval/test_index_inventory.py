"""Tests for index inventory and inventory-question detection."""

from __future__ import annotations

from ee_wiki.retrieval.index_inventory import (
    build_index_inventory,
    format_inventory_answer,
    is_inventory_question,
    parse_inventory_request,
    resolve_mentioned_project,
)


def test_is_inventory_question_positive() -> None:
    assert is_inventory_question("当前知识库有多少project")
    assert is_inventory_question("知识库有哪些项目？")
    assert is_inventory_question("How many projects are indexed?")
    assert is_inventory_question("list projects")
    assert is_inventory_question("logan有几个build")
    assert is_inventory_question("logan中有几个build")


def test_is_inventory_question_negative() -> None:
    assert not is_inventory_question("logan project 以太网 PHY 是什么")
    assert not is_inventory_question("STM32F407 主频多少")
    assert not is_inventory_question("Explorer 原理图 U14 在第几页")


def test_resolve_mentioned_project_from_indexed_names() -> None:
    assert resolve_mentioned_project("logan中有几个build", ["logan", "kingboo"]) == "logan"
    assert resolve_mentioned_project("当前知识库有多少project", ["logan", "kingboo"]) is None


def test_parse_named_project_build_question() -> None:
    request = parse_inventory_request(
        "logan中有几个build",
        known_projects=["logan", "kingboo", "global"],
    )
    assert request is not None
    assert request.kind == "builds"
    assert request.project == "logan"


def test_parse_project_count_question() -> None:
    request = parse_inventory_request("当前知识库有多少project")
    assert request is not None
    assert request.kind == "projects"
    assert request.project is None


def test_build_index_inventory_counts_projects(data_layout) -> None:
    chunks = [
        {"project": "global", "build": "global"},
        {"project": "global", "build": "global"},
        {"project": "kingboo", "build": "common"},
        {"project": "logan", "build": "p1"},
        {"project": "logan", "build": "p1"},
        {"project": "logan", "build": "common"},
    ]
    inventory = build_index_inventory(chunks, data_layout)
    assert inventory.chunk_count == 6
    assert inventory.product_count == 2
    by_name = {entry.project: entry for entry in inventory.projects}
    assert by_name["global"].is_enterprise is True
    assert by_name["global"].chunk_count == 2
    assert by_name["kingboo"].builds == ("common",)
    assert by_name["logan"].builds == ("common", "p1")
    assert by_name["logan"].chunk_count == 3


def test_format_inventory_answer_mentions_products(data_layout) -> None:
    inventory = build_index_inventory(
        [
            {"project": "global", "build": "global"},
            {"project": "kingboo", "build": "common"},
            {"project": "logan", "build": "p1"},
        ],
        data_layout,
    )
    answer = format_inventory_answer(inventory)
    assert "3** 个 project" in answer or "3 个 project" in answer
    assert "kingboo" in answer
    assert "logan" in answer
    assert "产品级 project" in answer


def test_format_project_builds_answer_for_logan(data_layout) -> None:
    inventory = build_index_inventory(
        [
            {"project": "logan", "build": "p1"},
            {"project": "logan", "build": "p1"},
            {"project": "logan", "build": "common"},
            {"project": "kingboo", "build": "common"},
        ],
        data_layout,
    )
    request = parse_inventory_request(
        "logan中有几个build",
        known_projects=[entry.project for entry in inventory.projects],
    )
    assert request is not None
    answer = format_inventory_answer(inventory, request)
    assert "logan" in answer
    assert "p1" in answer
    assert "kingboo" not in answer
    assert "硬件版本" in answer
    assert "common" in answer
