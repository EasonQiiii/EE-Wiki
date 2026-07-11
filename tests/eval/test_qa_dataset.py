"""Tests for the golden QA evaluation dataset."""

from __future__ import annotations

from ee_wiki.common.config import find_repo_root
from ee_wiki.common.eval_qa import load_qa_dataset


def test_qa_dataset_loads_and_validates() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())

    assert dataset.version == "1.0"
    assert len(dataset.cases) == 24
    assert len(dataset.mandatory_cases()) == 14
    assert len(dataset.negative_cases()) == 3


def test_stability_cases_include_paraphrases() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())
    stability = [case for case in dataset.cases if case.category == "stability"]

    assert len(stability) == 3
    for case in stability:
        assert case.paraphrases
        assert len(case.all_questions()) == 1 + len(case.paraphrases)


def test_negative_cases_expect_refusal() -> None:
    dataset = load_qa_dataset(repo_root=find_repo_root())

    for case in dataset.negative_cases():
        assert case.expect_refusal is True
        assert case.required_sources == ()
