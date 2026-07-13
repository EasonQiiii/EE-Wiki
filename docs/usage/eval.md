# RAG Evaluation Guide

How to run `scripts/eval_rag.py` — automated regression testing against the golden QA dataset in `docs/eval/`.

## What this is for

Use the eval CLI after changes to chunking, indexing, retrieval, scope cascade, prompts, or LLM backends. It scores the system against fixed questions with known answers so you can detect regressions before shipping.

**V3 note:** Graph neighbors/path, power tree, and rules evaluation are covered by focused unit/API tests (no live models in default `pytest`). Enable `retrieval.graph_enrichment` only when validating that optional context block; it defaults to off so golden RAG evals stay unchanged.

| Artifact | Path | Role |
|----------|------|------|
| Human-readable benchmark | [docs/eval/qa.md](../eval/qa.md) | Question list, expected answers, scoring rubric |
| Machine-readable dataset | [docs/eval/qa.yaml](../eval/qa.yaml) | Loaded by the eval runner; validated by `config/schema/qa_eval.schema.json` |
| Eval runner | `src/ee_wiki/common/eval_runner.py` | Scoring logic |
| CLI | `scripts/eval_rag.py` | Operator entry point |

## Prerequisites

```bash
cd /path/to/EE-Wiki
source .venv/bin/activate
pip install -e ".[dev,ml]"
```

Build indexes first — see [index.md](index.md):

```bash
python scripts/sync.py
```

### Models by mode

| Mode | Required models |
|------|-----------------|
| `retrieval` (default) | `embedding_model`, `reranker_model` |
| `generation` | Above + configured LLM (`generation.llm_backend`) |
| `both` | Same as `generation` |

For `generation` / `both`, ensure your LLM backend is running (e.g. `mlx-openai-server` when `llm_backend: openai`).

## Basic commands

From the repository root:

```bash
# Retrieval-only (fast; no LLM)
python3 scripts/eval_rag.py

# Full RAG pipeline (retrieval + LLM answer)
python3 scripts/eval_rag.py --mode both

# Generation layer only
python3 scripts/eval_rag.py --mode generation

# Mandatory cases only; exit 1 if below pass thresholds
python3 scripts/eval_rag.py --mandatory-only --fail-on-threshold
```

## Evaluation modes

| Mode | What it tests | Speed |
|------|---------------|-------|
| `retrieval` | Source hit@k, fact recall in top-k chunks | Fast (~30 s for 22 cases) |
| `generation` | LLM answer fact recall, citations, refusal behavior | Slow (LLM per question) |
| `both` | Full pipeline; overall pass requires retrieval **and** generation | Slowest |

Eval runs use a deterministic config: `query_rewrite`, `scope_inference`, `task_classification`, and `assistant_fallback` are disabled so scores reflect explicit `project` / `build` filters from the dataset.

## Scoring

### Retrieval (`retrieval` / `both`)

| Metric | Pass condition |
|--------|----------------|
| **Source hit@k** | At least one `required_sources` document appears in top-k chunks |
| **Fact recall** | `expected_facts` found in combined top-k chunk text (default ≥ 60%) |
| **Negative cases** | No forbidden scope; top rerank ≤ `--negative-rerank-ceiling` (default -2.0) |
| **Stability cases** | All paraphrases score consistently |

### Generation (`generation` / `both`)

| Case type | Pass condition |
|-----------|----------------|
| **Positive** | Not refused; answer fact recall ≥ threshold; citation hits `required_sources`; no `must_not_contain` |
| **Negative** | Refusal detected (`insufficient_context` or insufficient-knowledge phrasing); no hallucinated facts |

### Pass thresholds (default)

- Mandatory cases: ≥ **90%** pass rate
- Negative cases: **100%** pass rate

Use `--fail-on-threshold` to make the CLI return exit code `1` when thresholds are not met (suitable for CI).

## CLI reference

```bash
python3 scripts/eval_rag.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `retrieval` | `retrieval`, `generation`, or `both` |
| `--dataset` | `docs/eval/qa.yaml` | Path to golden QA YAML |
| `--top-k` | `retrieval.top_k_final` from config | Top-k for scoring and RAG context |
| `--fact-threshold` | `0.6` | Minimum fact recall (0.0–1.0) |
| `--negative-rerank-ceiling` | `-2.0` | Max rerank score for negative retrieval passes |
| `--case` | (all) | Repeatable; e.g. `--case Q-001 --case Q-003` |
| `--category` | (all) | Repeatable; `datasheet`, `schematic`, `scope`, `negative`, … |
| `--mandatory-only` | off | Run only mandatory cases (14 of 26) |
| `--json` | off | Print JSON report to stdout |
| `--output PATH` | — | Write JSON report to file |
| `--fail-on-threshold` | off | Exit 1 when mandatory/negative thresholds fail |
| `-v` / `--verbose` | off | Enable DEBUG logging |

## Example workflows

### After retrieval changes

```bash
python3 scripts/eval_rag.py --mandatory-only
```

### Debug a single failing case

```bash
python3 scripts/eval_rag.py --case Q-015 --json
python3 scripts/query.py "在 logan p1 上下文中，这块板的以太网 PHY 芯片型号应优先引用哪份文档？" \
  --project logan --build p1
```

### Save a baseline report

```bash
python3 scripts/eval_rag.py --mode both \
  --output reports/rag-eval-$(date +%Y%m%d).json \
  --json
```

### Category-focused run

```bash
python3 scripts/eval_rag.py --category negative --mode both
python3 scripts/eval_rag.py --category stability
```

## Reading the text report

```
EE-Wiki RAG eval (both)
dataset=1.0 corpus=2026-07-10T03:10:47Z top_k=8
summary: passed 9/13 mandatory=69% negative=67% source_hit=80% generation=62%

ID       PASS  SRC  FACT  STAB  NEG  Title
Q-001    Y     Y    Y     Y     Y    STM32F407 核心参数
  - hit@8=True rank=1 facts=3/3 rerank=3.092
    Q: STM32F407ZGT6 的最高 CPU 主频...
  - gen_pass=True facts=2/3 citation=True refusal=False
    Q: STM32F407ZGT6 的最高 CPU 主频...
    A: STM32F407ZGT6 的最高 CPU 主频为 168 MHz...
```

| Column | Meaning |
|--------|---------|
| `PASS` | Overall pass for this case |
| `SRC` | Source hit@k |
| `FACT` | Fact recall in chunks |
| `STAB` | Stability across paraphrases |
| `NEG` | Negative-case retrieval guard |
| `GEN` / `ANS` / `CIT` / `REF` | Generation-only columns (generation pass, answer facts, citation, refusal) |

## Maintaining the benchmark

1. After a large ingest / reindex, update the corpus snapshot at the top of [qa.md](../eval/qa.md) and in [qa.yaml](../eval/qa.yaml) (`corpus.chunk_count`, `corpus.built_at`). Phase A (2026-07-11): 4,676 chunks; removed Q-002/Q-014; added Q-023–Q-026.
2. Add 2–3 cases per new project or document type; keep the same fields as existing entries in `qa.yaml`.
3. After V2 metadata upgrades (schematic `pages`, datasheet structured fields, FA keywords, `components.json`), re-ingest + re-index before eval — see [mcp.md](mcp.md).
4. Run `pytest tests/eval/` to validate YAML schema and scoring helpers.
5. Re-run `python3 scripts/eval_rag.py --mandatory-only` and compare against your last saved JSON report.

Programmatic access:

```python
from ee_wiki.common.eval_qa import load_qa_dataset
from ee_wiki.common.eval_runner import run_eval, build_eval_config
from ee_wiki.common.config import load_config
from ee_wiki.generation.service import RagService

config = build_eval_config(load_config())
dataset = load_qa_dataset()
service = RagService.from_config(config)
service.engine.load_index()
report = run_eval(dataset, mode="both", rag_service=service)
print(report.mandatory_pass_rate)
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| `QA eval dataset not found` | Run from repo root; confirm `docs/eval/qa.yaml` exists |
| `No processed documents` / empty index | Run `python scripts/sync.py` first |
| Generation mode hangs or errors | LLM backend reachable? See [local-setup.md](local-setup.md) |
| All negative cases fail in retrieval mode | Try `--negative-rerank-ceiling -1.0` temporarily; may indicate weak-rerank calibration |
| Fact recall fails but answer looks correct | Golden `expected_facts` may use different wording (e.g. `1 Mbyte` vs `1024 Kbytes`); update `qa.yaml` or rely on normalized matching (`1.2 A` ≈ `1.2A`) |
| Negative case fails with global filter | Ensure `forbidden_scope` is set only for non-existent scopes (`logan/p2`, `apollo/evt`), not for normal query filters like `global/global` |
| Q-015 / Q-016 fail on meta-questions | Rephrase to retrieval-friendly factual queries; scope isolation uses `forbidden_sources` for cross-project leakage |

## Related docs

- [qa.md](../eval/qa.md) — full golden QA list and manual scoring rubric
- [query.md](query.md) — `query.py` and `ask.py` for ad-hoc debugging
- [index.md](index.md) — building indexes before eval
- [data-flow.md](../architecture/data-flow.md) — retrieval and generation pipeline
