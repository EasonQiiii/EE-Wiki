"""Load and validate the RAG golden QA evaluation dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import jsonschema
import yaml

from ee_wiki.common.config import find_repo_root
from ee_wiki.common.errors import ConfigError

EvalCategory = Literal[
    "datasheet",
    "schematic",
    "sop",
    "fa",
    "scope",
    "platform",
    "negative",
    "stability",
]

ScopeLabel = Literal["build", "common", "product_common", "global"]

DEFAULT_QA_PATH = Path("docs/eval/qa.yaml")
DEFAULT_SCHEMA_PATH = Path("config/schema/qa_eval.schema.json")


@dataclass(frozen=True)
class EvalFilters:
    """Metadata filters suggested for a golden QA case."""

    project: str
    build: str
    product: str = ""


@dataclass(frozen=True)
class EvalCase:
    """One golden question/answer pair for RAG evaluation."""

    id: str
    title: str
    category: EvalCategory
    mandatory: bool
    filters: EvalFilters | None
    scope_label: ScopeLabel | None
    question: str
    expected_answer: str
    required_sources: tuple[str, ...] = ()
    optional_sources: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()
    paraphrases: tuple[str, ...] = ()
    expect_refusal: bool = False
    forbidden_scope: EvalFilters | None = None
    forbidden_sources: tuple[str, ...] = ()

    def all_questions(self) -> tuple[str, ...]:
        """Return the primary question plus any stability paraphrases.

        Returns:
            Tuple of query strings to run for this case.
        """
        if not self.paraphrases:
            return (self.question,)
        return (self.question, *self.paraphrases)


@dataclass(frozen=True)
class EvalCorpus:
    """Snapshot metadata for the indexed knowledge base."""

    manifest: str
    chunk_count: int
    built_at: str
    coverage: tuple[str, ...]


@dataclass(frozen=True)
class EvalDataset:
    """Full golden QA dataset with scoring metadata."""

    version: str
    corpus: EvalCorpus
    cases: tuple[EvalCase, ...] = ()
    schema_path: Path | None = None

    def mandatory_cases(self) -> tuple[EvalCase, ...]:
        """Return cases that must pass for an evaluation run.

        Returns:
            Tuple of mandatory evaluation cases.
        """
        return tuple(case for case in self.cases if case.mandatory)

    def negative_cases(self) -> tuple[EvalCase, ...]:
        """Return negative cases that must be refused.

        Returns:
            Tuple of negative evaluation cases.
        """
        return tuple(case for case in self.cases if case.category == "negative")


def _parse_filters(raw: dict[str, Any] | None) -> EvalFilters | None:
    if raw is None:
        return None
    return EvalFilters(
        project=str(raw["project"]),
        build=str(raw["build"]),
        product=str(raw.get("product", "") or ""),
    )


def _parse_case(raw: dict[str, Any]) -> EvalCase:
    scope = raw.get("scope_label")
    return EvalCase(
        id=str(raw["id"]),
        title=str(raw["title"]),
        category=raw["category"],
        mandatory=bool(raw["mandatory"]),
        filters=_parse_filters(raw.get("filters")),
        scope_label=scope,
        question=str(raw["question"]),
        expected_answer=str(raw["expected_answer"]).strip(),
        required_sources=tuple(raw.get("required_sources") or ()),
        optional_sources=tuple(raw.get("optional_sources") or ()),
        must_not_contain=tuple(raw.get("must_not_contain") or ()),
        expected_facts=tuple(raw.get("expected_facts") or ()),
        paraphrases=tuple(raw.get("paraphrases") or ()),
        expect_refusal=bool(raw.get("expect_refusal", False)),
        forbidden_scope=_parse_filters(raw.get("forbidden_scope")),
        forbidden_sources=tuple(raw.get("forbidden_sources") or ()),
    )


def _parse_dataset(raw: dict[str, Any]) -> EvalDataset:
    corpus_raw = raw["corpus"]
    corpus = EvalCorpus(
        manifest=str(corpus_raw["manifest"]),
        chunk_count=int(corpus_raw["chunk_count"]),
        built_at=str(corpus_raw["built_at"]),
        coverage=tuple(corpus_raw["coverage"]),
    )
    cases = tuple(_parse_case(item) for item in raw["cases"])
    return EvalDataset(version=str(raw["version"]), corpus=corpus, cases=cases)


def load_qa_eval_schema(
    schema_path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Load the JSON Schema for the QA evaluation dataset.

    Args:
        schema_path: Optional explicit schema path.
        repo_root: Repository root used when ``schema_path`` is relative.

    Returns:
        Parsed JSON Schema document.

    Raises:
        ConfigError: If the schema file cannot be read or parsed.
    """
    root = repo_root or find_repo_root()
    path = schema_path or (root / DEFAULT_SCHEMA_PATH)
    if not path.is_file():
        raise ConfigError(f"QA eval schema not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid QA eval schema JSON: {path}") from exc


def validate_qa_eval_data(
    data: dict[str, Any],
    schema: dict[str, Any] | None = None,
    *,
    schema_path: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    """Validate raw QA dataset data against the JSON Schema.

    Args:
        data: Parsed YAML/JSON dataset payload.
        schema: Optional pre-loaded schema. Loaded from disk when omitted.
        schema_path: Schema path used when ``schema`` is omitted.
        repo_root: Repository root for relative schema resolution.

    Raises:
        ConfigError: If validation fails.
    """
    schema_doc = schema or load_qa_eval_schema(schema_path, repo_root=repo_root)
    try:
        jsonschema.validate(data, schema_doc)
    except jsonschema.ValidationError as exc:
        raise ConfigError(f"QA eval dataset failed schema validation: {exc.message}") from exc


def load_qa_dataset(
    dataset_path: Path | None = None,
    *,
    schema_path: Path | None = None,
    repo_root: Path | None = None,
    validate: bool = True,
) -> EvalDataset:
    """Load the golden QA dataset from ``docs/eval/qa.yaml``.

    Args:
        dataset_path: Optional explicit dataset path.
        schema_path: Optional explicit schema path for validation.
        repo_root: Repository root used for default paths.
        validate: Whether to validate against ``qa_eval.schema.json``.

    Returns:
        Parsed and optionally validated evaluation dataset.

    Raises:
        ConfigError: If the dataset is missing, malformed, or invalid.
    """
    root = repo_root or find_repo_root()
    path = dataset_path or (root / DEFAULT_QA_PATH)
    if not path.is_file():
        raise ConfigError(f"QA eval dataset not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid QA eval YAML: {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"QA eval dataset must be a mapping: {path}")

    if validate:
        validate_qa_eval_data(
            raw,
            schema_path=schema_path,
            repo_root=root,
        )

    dataset = _parse_dataset(raw)
    resolved_schema = schema_path or (root / DEFAULT_SCHEMA_PATH)
    return EvalDataset(
        version=dataset.version,
        corpus=dataset.corpus,
        cases=dataset.cases,
        schema_path=resolved_schema if validate else None,
    )
