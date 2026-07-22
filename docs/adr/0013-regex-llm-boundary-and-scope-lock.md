# 0013. Regex/LLM Boundary, TurnScope Lock, and Connectivity Authority

Date: 2026-07-21
Status: proposed (draft for review — work items remain in Recommended, not yet promoted to hard rules)

## Context

Three precision risks have surfaced while hardening the chat pipeline (ADR 0008 / 0012) and the FA agent (fa-session.md, implementation plan):

1. **Regex doing semantic work.** A repo-wide audit found ~100+ `re.compile` / `re.search` sites; **~8 groups / ~14 sites** perform *semantic* classification (intent, FA-vs-wiki, vague, log PASS/FAIL, failure-mode, inventory-kind) that regex cannot do reliably — especially for Chinese paraphrases and bus subscripts like `NAME<1>`. The right tool is the local LLM + a structured `prompts/` template, which we already use for `classify_fa_mode`.
2. **TurnScope double-inference drift.** Scope (product/project/build) was historically re-inferred in multiple places (API body, prepare, retrieval merge, FA session, `ScopeEnvelope`). ADR 0012 §6 fixed the contract — lock once at the chat entry — but `ensure_fa_session` / tool paths still *could* drift back into NL inference. This is a precision defect: a second, inconsistent inference can change the build a trace runs against.
3. **Connectivity prose rewrite.** Even with the authoritative gate, hybrid RAG / Supervisor prose must never re-narrate a board-verified pin list into an invented 起点→终点 signal path.

AGENTS.md §2 ("Precision over latency") already documents the regex/LLM hard boundary and the debt inventory. This ADR **codifies** that boundary as a migration checklist and promotes two precision-critical rules (TurnScope single-point lock, authoritative connectivity direct output) to first-class decisions. It deliberately keeps the actionable migration list in **Recommended** — these are planned changes, not yet promoted to hard architectural rules.

## Decision

### 1. TurnScope single-point lock (precision-critical, first-class)

Scope inference (product/project/build from the question) must run **exactly once**, at the chat entry (`api/routes/chat.py`), and then **lock** for the whole turn.

- The chat entry calls `merge_scope_from_question` once when API body scope is incomplete, then locks (`ADR 0012 §6`).
- `ensure_fa_session(...)` and every ToolBus handler / tool path **must read** the locked scope via `ctx.resolve_scope(...)` and **must NOT** perform a second NL inference for the same turn.
- `ensure_fa_session` may inherit axes from the prior FA header (`**EE-Wiki scope:**` line) only when the caller left them unset (DialogScope), per ADR 0012 §6. That is header-parse inheritance, **not** NL inference.
- Rationale: this is directly tied to **「准」(precision)**. A second inference can resolve a different build than the locked one, silently changing which schematic/sidecar a `trace_net` runs against. The chat entry is the single source of truth.

> Previously this was only a one-line note in AGENTS.md §2 ("Keep as regex"). It is now a first-class rule.

### 2. Authoritative connectivity direct output (no prose rewrite)

Trace / connectivity questions are answered by the deterministic gate
`ee_wiki.connectivity.chat.answer_trace_question`, invoked at the **chat gate**
(`api/routes/chat.py`, branch `connectivity_authority`) **before** FaMode /
Supervisor / hybrid RAG.

- The gate returns **either** a board-verified pin table (**CAD netlist only**)
  **or** an explicit refusal (no sidecar / insufficient authority / not found).
  BoardView (`.brd`) is *advisory reference* and never grounds a trace (see §4).
- Hybrid RAG / Supervisor prose **must never** rewrite that pin list into an
  invented 起点→终点 signal-path narrative, nor substring-expand a bus base name
  into `NAME<0>…NAME<n>` (AGENTS.md §2; `connectivity/chat.py` already carries the
  `_format_found` disclaimer forbidding this).
- `answer_trace_question` is the single authority; `trace_net` / `connector_pins`
  tools remain authoritative for agent turns. The chat gate exists so hybrid prose
  can never invent pin paths when intent detection would otherwise miss tools.

### 3. Regex = structural tokens only (boundary reference)

The canonical boundary lives in **AGENTS.md §2** ("Regex vs LLM (hard boundary)").
Summary:

- **Regex MAY do:** `rdar://`/Radar ids/URLs/path segments; own-output markdown
  headers; designator/voltage *shapes* once a token is known; config-driven scope
  alias maps (after the TurnScope lock); deterministic net/refdes *candidate*
  extraction (`_NET_TOKEN` / `_REFDES_TOKEN`) used in exact sidecar lookup.
- **Regex MUST NOT do:** intent classification (trace vs chitchat, FA vs wiki,
  vague), peeling net/refdes *meaning* from natural language (esp. bus `NAME<1>`),
  judging log/doc lines as PASS vs FAIL, FA turn verbs as the sole router, or
  keyword lists that preempt an existing LLM classifier.

### 4. BoardView (`.brd`) is advisory reference, not a trace source (2026-07-21)

BoardView `.brd` is **kept** (parsed, merged into `*.connectivity.json`, available
for retrieval / net-membership / probe-point reference) but is **removed** from
`connectivity.authoritative_evidence`. Only `cad_netlist` (`*.net` / KiCad /
Altium) may ground an answer-grade trace.

- **Why keep:** `.brd` carries real logical pin↔net bindings and (often) test-point
  / probe-point data that a schematic netlist may omit — useful *reference* for an
  FA engineer ("where do I probe net X?").
- **Why not authoritative:** it is a logical pin↔net list, **not** copper geometry.
  It cannot deliver accurate physical track routing, and presenting it as verified
  trace overstates its reliability. The user explicitly decided: *keep it, but not
  use it for trace tracking.*
- **Consequence:** a board with only a `.brd` companion (no CAD netlist) now gets an
  **authoritative refusal** for trace queries, with the boardview pins surfaced
  under `advisory_pins` for transparency. The netlist (`cad_netlist`) is the sole
  board-verified trace source.
- Enforced at `ConnectivityQuery.resolve_trace` (`connectivity/authority.py`):
  `DEFAULT_AUTHORITATIVE_EVIDENCE = {"cad_netlist"}`; `config/default.yaml`
  `authoritative_evidence` lists only `cad_netlist`.

## Recommended (planned work — keep here, do not promote to hard rules yet)

Migrate semantic regex sites to LLM + `prompts/`, in this order, each with golden
tests on **real Chinese + English utterances** (see Testing). Owner: implementer of
each site; reviewer: human lab.

| Pri | Location | Current regex job | Target |
|-----|----------|-------------------|--------|
| **1** | `connectivity/intent.py` — `_CONNECT_PATTERNS`, `detect_trace_intent` | Full-trace vs chitchat; promote net | LLM structured `KIND:` + `NET:` (keep `NAME<1>`) + optional `PIN:` |
| **1** | `agents/fa_mode.py` — `_WIKI_CONNECTIVITY`, `_FA_FAILURE_CUES` | FA vs Wiki before `classify_fa_mode` | Keep structural fast path (`rdar://`, own FA headers) only; ambiguous → `classify_fa_mode` alone |
| **2** | `integrations/radar/attachments.py` — `_PASS_LINE`, `_FAIL_LINE` | Line PASS/FAIL | LLM line verdict + summary for "分析 log" |
| **2** | `integrations/radar/attachments.py` — `_DOWNLOAD_INTENT`, `_CONTENT_INTENT` | Download vs read-content | LLM FA action / slot classify |
| **2** | `integrations/fa_chat.py` — `_CHECKIN_VERB`, `_EVIDENCE_MARKERS`, … | FA turn routing | LLM `KIND:` for FA turns |
| **3** | `retrieval/query_intent.py` — `is_board_interface_pin_query` | Board pin vs datasheet pin | LLM `query_kind` |
| **3** | `agents/clarify.py` — `_VAGUE` | Underspecified utterance | LLM + history: enough info? |
| **3** | `retrieval/index_inventory.py` — count patterns | Inventory questions | LLM `inventory{build\|project}` |
| **4** | `ingestion/keywords.py` — `_FAILURE_MODE_RE`, `_SYMPTOM_RE` | FA keyword tags | Offline ingest LLM tags (batch) |

TurnScope hardening (Decisions 1–2) is **already implemented** at the chat entry;
the remaining action is a regression guard test (see Testing) plus keeping the
contract explicit as code evolves.

## Testing (gold-sample requirement)

Any change to a **semantic classifier** (intent, FA-vs-wiki, vague, PASS/FAIL,
inventory-kind, skill selection) must be validated with:

1. **Real Chinese + English utterances as gold samples** — not invented toy
   strings. Example full-trace gold sample with a bus subscript:
   - CN: `logan p1 上 U8600 的 I2C_SCL<1> 完整 trace 到哪些 pin？`
   - EN: `logan p1 U8600 I2C_SCL<1> full net trace to which pins?`
   The gold sample must exercise the bus-subscript `NAME<1>` case (the exact case
   regex historically strips — see `connectivity/intent.py`).
2. **No mock-keyword-only validation.** A semantic change must include at least
   one real-utterance golden test per classifier; a mock that returns a fixed
   `KIND:`/`MODE:` line is **not sufficient** evidence the classifier works on real
   language. Mocked LLM lines are acceptable only to isolate routing, never as the
   sole proof of classification correctness.
3. **TurnScope guard:** a test must prove `ensure_fa_session` never re-infers —
   caller-passed `product`/`project`/`build` are returned unchanged and
   `merge_scope_from_question` / `extract_scope_rules` are never called by it.

## Pre-merge checklist (one line)

> **No new semantic regex gates.** Any semantic classification (intent / FA-vs-wiki /
> vague / PASS-FAIL / inventory-kind / skill routing) must use the local LLM +
> `prompts/`, never a newly added `re` rule. Structural-token regex is exempt.

## Out of scope / non-goals

- Promoting the Recommended migrations to hard rules in this ADR (they stay planned).
- Changing ADR 0008 write bans, ToolBus sandbox, or role YAML layout.
- Debate-style multi-agent; DialogScope memory redesign beyond FA.

## Consequences

### Positive

- Precision-critical rules (TurnScope lock, connectivity authority) are explicit and regression-guarded.
- One canonical regex/LLM migration checklist; reviewers know exactly what "semantic regex" means and where debt lives.
- Testing bar prevents silent semantic regressions masked by mock keywords.

### Negative / limits

- Migrations (Recommended) add LLM calls on some paths; latency cost accepted where precision matters (matches ADR 0012 §4 thresholds).
- Evidence-only generation when retrieve is empty remains an interim citation hole (ADR 0012 follow-up).

## References

- [AGENTS.md](../../AGENTS.md) §2 — "Precision over latency" (regex/LLM hard boundary + debt inventory)
- [ADR 0012](0012-chat-pipeline-grounding.md) §5 (connectivity gate), §6 (TurnScope vs DialogScope)
- [ADR 0009](0009-multi-source-schematic-map.md) — connectivity authority
- [fa-agent-implementation-plan.md](../architecture/fa-agent-implementation-plan.md) §9 (acceptance; gold-sample testing note)
