# D-AI Roadmap (Generation 1)

Scope: D-AI generation 1 only. **D-AI 2.0 is out of scope** and is not planned here.

Rules for every phase:

- A phase starts only after the previous phase's exit criteria are met **and** you approve.
- No dependency is installed without explicit approval.
- Nothing outside the `D-AI/` directory is modified.
- Each phase ends with: tests passing on Linux + Termux (Windows when available), docs updated.

## Status

Phases 0 to 8 are implemented in v1.0.0 and covered by 69 offline tests. Phase 9 is partly done:
the documentation is complete, but Windows/Termux/Python 3.13 verification, calibration on
labelled real-world data, and a security review remain **open** (see ARCHITECTURE.md, Appendix B).

## PR2 (v0.2) work items

| Item | Status |
|---|---|
| Keep source reliability / evidence strength / evidence balance separate (`dai.result/2`) | done, 79 tests pass |
| 01 Search relevance | open |
| 02 Independent source grouping | open |
| 03 Numeric context analysis | open |
| Real run on Termux; test with real internet sources | open (Critical) |
| Turkish claim extraction on real texts; trust-score calibration | open (High) |
| Paraphrased same-claim matching; license choice | open (Medium) |

## Pr3 (from the real Windows runs of 14 Nov)

| Finding in the real output | Change |
|---|---|
| Crash `cannot convert 'NoneType' to bytes` with 6 URLs | cache rows are read inside the DB lock (threads raced on one connection); a NULL body is a cache miss |
| "How tall is Everest?" returned "named after George Everest" and dropped the 8,848.86 m sentence | question profile (quantity/date/open, unit, asked property, names, years); a quantity question needs a number with the right unit; the page title can supply the subject; a number next to a different name is demoted |
| "population of Norway" fetched "Norwegian Minnesotans" | short search queries (content words, bare names) and results ranked by title match |
| `--agent` used all 16 sources in round 1 | first round limited to `max_sources`; warns when too few independent groups exist |
| `[25]` footnotes in sentences and as numbers; hatnotes, captions, "FILE - ..." as claims; "Mt." split a sentence | markers stripped, non-claim lines dropped, abbreviations extended |
| "5.91 billion km; 3.67 billion mi" parsed as 5.9e21; feet not a unit; 1856/1453 not a date | units must follow the number directly; ft/in/yd added; pre-1900 years are dates when a year cue is present |
| 8,840 vs 8,842 shown as "same numbers" | new "approximate numeric match" state and an `approx` note |
| One shared word ("tower") created contradictions/clusters between unrelated facts | stronger same-subject requirement |
| 3 copies of one AP story shown as 3 supporters | `copies` note: "3 documents count as 1 independent source" |
| `127.0.0.1` / `ftp://` reported as "disallowed by robots.txt"; a soft-404 page counted as a source | URL checks run before robots with a `blocked:` message; error-titled short pages are skipped |
| TR question on EN pages: silent empty result | explicit language-mismatch warning |

Still open: source reliability calibration (unrated domains score about 73-75 because the other
signals are all 1.0), cross-language matching, claims whose subject is a *different* thing in
the same sentence, and a provider beyond Wikipedia that needs no key.

## Phase 0: Design (done)

Deliverables: `ARCHITECTURE.md`, `ROADMAP.md`, `README.md`, proposed structure.

Exit criteria: you approve the architecture and answer the open decisions
(search provider, test runner, packaging, output language, fate of the prototype).

## Phase 1: Foundation

- `pyproject.toml` (stdlib-only runtime), `src/dai/` skeleton, `python -m dai`
- `core/models.py`, `config.py` (layered), `paths.py`, `errors.py`
- `storage/db.py` + schema, `i18n/tokenize.py` + en/tr stop-word files
- CLI skeleton with subcommands (no logic yet), UTF-8 stdout handling
- Test harness and import-rule test

Exit: `dai --help` works on Termux and Linux; DB create/open/close tested; tokenizer tests pass
for English and Turkish.

## Phase 2: Discovery, ingestion, extraction

- `discovery`: `manual_urls` provider and one approved search provider
- `ingest`: fetcher, robots.txt, rate limit, content-addressed cache, SSRF guard, size/time caps
- `extract`: main-text extraction and metadata (title, author, date, publisher, language)
- Commands: `dai fetch`

Exit: fixture pages extract correctly; cache hit/miss tested; unsafe URLs rejected;
fully offline test run.

## Phase 3: Claims

- Sentence segmentation (abbreviation-aware, Turkish and English)
- Claim typing (fact / quote / opinion / forecast), subject/predicate/value extraction
- Number, unit and date normalization
- Command: `dai claims`

Exit: labeled sample of at least 200 sentences, claim extraction precision reported and
documented; known failure modes listed in the docs.

## Phase 4: Trust

- Subscores, domain tiers (default file plus user-editable), explainable `TrustReport`
- Command: `dai trust`, `dai sources`
- Calibration: small hand-labeled set of domains/pages to tune weights

Exit: scores reproducible; each score lists contributing signals; weights documented as heuristic.

## Phase 5: Analysis

- Clustering (deterministic), ordered relation rules, independence detection
- Evaluation set of labeled claim pairs; precision/recall tracked per relation kind

Exit: contradiction/update/agreement metrics reported; regression tests for each known failure
(e.g. negation vs high overlap, empty subject, syndicated copies).

## Phase 6: Synthesis and rendering

- Aggregation, confidence model, statement selection and ranking
- Shared reference registry; JSON renderer (stable schema, versioned); text renderer
- Command: `dai research --url ...`

Exit: end-to-end run from fixtures produces golden JSON and text; schema documented.

## Phase 7: Pipeline integration and audit

- Orchestrator with warnings, partial-failure handling, per-stage timing and stats
- Full `runs` persistence, command: `dai audit`, reproducible re-run from cache
- Meaningful exit codes

Exit: any past run can be inspected and re-rendered offline.

## Phase 8: Agent layer

- Tool interfaces, deterministic planner/state machine, budgets and stop rules
- Follow-up search on contradictions or low independence, full step logging
- Command: `dai research --agent`

Exit: agent runs are reproducible given cache; budget limits enforced; every step in the audit trail.

## Phase 9: Hardening and 1.0

- Windows verification, Termux install guide, performance pass on pure-Python hot spots
- Security review (network, parsing, storage), documentation completion, versioned release 1.0

Exit: install and run documented on all three platforms; known limitations section current.

## Deliberately not in this roadmap

- Language models, embeddings, neural semantic matching
- JavaScript rendering, paywall bypass, login automation
- GUI or web frontend
- Anything belonging to D-AI 2.0

## Decision gates (need your input)

| Gate | Needed before |
|---|---|
| Approve architecture and open decisions | Phase 1 |
| Search provider and any API key handling | Phase 2 |
| Test runner (`unittest` vs `pytest`) | Phase 1 |
| Any third-party dependency, one by one | The phase that needs it |
| Public release and license | Phase 9 |
