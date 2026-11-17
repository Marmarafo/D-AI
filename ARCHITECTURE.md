# D-AI Architecture (Generation 1)

Status: **implemented (v1.0.0).** This document keeps the original design reasoning and records, in
Appendix B, where the implementation differs from the proposal and what is not yet verified.
Scope: D-AI generation 1 only. D-AI 2.0 is a separate future generation and is out of scope.

## 1. What D-AI is (and is not)

D-AI is an **algorithmic research system**. Given a question, it gathers web sources, extracts
claims, scores source reliability, compares sources, detects contradictions, and produces an
answer in which every statement is tied to quoted evidence.

It is **not** a language model. It does not generate free text. Every sentence in an answer is
a claim lifted from a source (with its quote and URL), never a paraphrase invented by D-AI.

Consequences we accept on purpose:

- Answers are **"supported by these sources"**, not **"true"**. D-AI reports agreement,
  dissent and uncertainty; it does not establish truth.
- Understanding is **lexical and structural** (tokens, numbers, dates, negation, attribution),
  not semantic. Paraphrases with little word overlap will be missed.
- Every decision is **explainable**: each relation, score and confidence value carries the
  signals that produced it.

## 2. Design principles

1. **Deterministic and auditable.** Same inputs plus same cached pages give the same output.
   Every run is stored with config snapshot, fetched-content hashes and intermediate results.
2. **Standard library first.** Pure-Python only. No compiled dependencies (lxml, numpy, etc.)
   because they are painful or impossible to build in Termux.
3. **Narrow interfaces, replaceable parts.** Search providers, fetchers, extractors, scorers
   are behind small `Protocol` interfaces.
4. **Data flows one way** through immutable dataclasses; stages do not reach into each other.
5. **Provenance everywhere.** A claim always knows its document, character offsets and quote.
6. **Fail soft.** A dead URL or parse error becomes a recorded warning, not a crash.
7. **Offline-testable.** The whole pipeline runs from saved HTML fixtures with no network.

## 3. Pipeline

```
question
  │
  ▼
[1 Plan]        query analysis, language detection, query variants, source budget
  ▼
[2 Discover]    SearchProvider(s) and/or user-supplied URLs  → candidate URLs
  ▼
[3 Ingest]      robots.txt, rate limit, fetch, cache, size/time limits  → RawPage
  ▼
[4 Extract]     HTML → main text + metadata (title, author, date, publisher) → Document
  ▼
[5 Claims]      sentence segmentation, claim typing, normalization
                (numbers, units, dates, subject/predicate/value)  → Claim
  ▼
[6 Trust]       per-source reliability score with subscores  → TrustReport
  ▼
[7 Analyze]     clustering of similar claims, pairwise relations
                (agreement / contradiction / update / nuance)  → Cluster, Relation
  ▼
[8 Independence] collapse syndicated or copied sources into one voice
  ▼
[9 Synthesize]  per cluster: supporting vs dissenting evidence, confidence  → Statement
  ▼
[10 Render]     structured JSON first, human text second
  ▼
[11 Audit]      everything above persisted in SQLite, inspectable by run id
```

Stages 5, 7, 8, 9 are pure functions (no I/O) and carry most of the logic, so they are the most
heavily unit-tested.

## 4. Core data model

All are frozen dataclasses with `slots=True` in `dai/core/models.py`.

| Type | Key fields |
|---|---|
| `RawPage` | url, final_url, status, content_type, body_bytes, fetched_at, content_hash, from_cache |
| `Document` | url, domain, title, author, published, language, text, fetched_at |
| `Claim` | text, normalized, claim_type, subject, predicate, value, numbers, dates, negated, doc_url, char_start, char_end |
| `TrustReport` | url, score (0-100), tier, subscores (dict), signals (list) |
| `Evidence` | claim, url, domain, title, quote, reliability (source), strength (this quote) |
| `Relation` | a, b, kind, signals (list of strings) |
| `Cluster` | key, claim refs |
| `Statement` | text, claim_type, balance (evidence balance), cluster_size, supporting, dissent, notes |
| `Run` | id, question, config_snapshot, started/finished, stats, errors |

Conventions:

- **One scale per concept.** Trust and confidence are both stored as floats in `[0, 1]` and
  formatted as percent only at render time. (The prototype mixed scales; see Appendix A.)
- Dates are `datetime.date`/`datetime` in UTC; unknown stays `None`, never a guessed value.

## 5. Project structure (as implemented)

```
D-AI/
├── README.md  ARCHITECTURE.md  ROADMAP.md  config.example.toml  pyproject.toml
├── run_dai.py            # run without installing
├── run_tests.py          # offline test suite (unittest)
├── src/dai/
│   ├── __init__.py  __main__.py  config.py  paths.py
│   ├── core/        models.py  errors.py  pipeline.py   (ResearchSession, run_research)
│   ├── discovery/   base.py  providers.py               (wikipedia, searxng, brave)
│   ├── ingest/      urls.py  safety.py  http.py  robots.py  ratelimit.py  fetch.py
│   ├── extract/     html_extract.py                     (html.parser based)
│   ├── claims/      normalize.py  segment.py  relevance.py
│   ├── trust/       tiers.py  score.py
│   ├── analysis/    relations.py  cluster.py  independence.py
│   ├── synthesis/   confidence.py  aggregate.py
│   ├── render/      refs.py  json_out.py  text_out.py
│   ├── storage/     db.py                               (SQLite: pages, tiers, runs)
│   ├── i18n/        stopwords.py  tokenize.py
│   ├── agents/      tools.py  planner.py                (deterministic agent)
│   └── cli/         main.py
└── tests/           helpers.py  test_text.py  test_analysis.py  test_ingest.py
                     test_pipeline.py  test_misc.py
```

Module dependency rule (enforced by a small test that checks imports):

```
cli → core.pipeline → {discovery, ingest, extract, claims, trust, analysis, synthesis, render, storage}
all packages → core.models, i18n, config
no package imports cli; render never imports analysis; analysis never imports ingest
```

## 6. Key design decisions

### 6.1 Standard library only
`urllib.request`, `html.parser`, `sqlite3`, `json`, `argparse`, `re`, `unicodedata`,
`dataclasses`, `concurrent.futures`, `difflib`, `hashlib`, `unittest`.

- **Why:** Termux has no reliable wheels for lxml/numpy/scipy; fewer dependencies means fewer
  breakages on three platforms.
- **Cost:** `html.parser` is slower and less forgiving than lxml; no HTTP/2, no connection
  pooling niceties. Acceptable at research-tool volumes (tens of pages per query).
- **Windows note:** `zoneinfo` needs the `tzdata` package on Windows. We avoid timezone
  database use; all dates are UTC or naive-as-published. Any exception to the stdlib-only rule
  is requested for approval individually.

### 6.2 Search discovery is the weakest link
Web search normally needs an API or scraping.

| Option | Pros | Cons |
|---|---|---|
| User-supplied URLs | Zero dependency, deterministic | Not automatic |
| Self-hosted SearxNG | Free, aggregated | Needs an instance |
| Wikipedia / Wikidata APIs | Free, stable | Narrow coverage |
| Commercial search API (Brave, etc.) | Reliable | Key and quota |
| Scraping a search engine's HTML | No key | Fragile, likely against terms of service |

**Decision:** ship `manual_urls` and one API-style provider behind the `SearchProvider`
Protocol. Scraping search engines is not a default. Provider choice is a Phase 2 approval gate.

### 6.3 Claims, not summaries
The unit of work is a **claim** (a sentence-level assertion with subject / predicate / value /
numbers / dates / negation). Output statements are claims selected and ranked, never rewritten.
This is what keeps D-AI honest without a language model.

### 6.4 Relation classification (lexical, ordered rules)
Within a cluster, each pair is classified by an **ordered** rule list; the first rule that fires
wins and its signals are recorded:

1. identical normalized text → agreement
2. same fact with different dates → **update** (not conflict)
3. same slot with different numbers → contradiction
4. negation present in exactly one claim and high overlap → contradiction
5. very high overlap and no conflict signal → agreement
6. partial overlap without conflict → nuance
7. otherwise → unrelated

Rule order matters: conflict checks must precede the "high overlap = agreement" shortcut,
otherwise "X is approved" / "X is not approved" can be classed as agreement.

### 6.5 Source independence
Ten copies of one wire story are **one** source. Independence is estimated from:

- same registered domain or known publisher group
- near-duplicate text (word shingles + Jaccard or simhash)
- attribution cues ("according to Reuters", "AP reported")
- identical quote sets

Dependent sources are collapsed into one voice for confidence; they remain visible in the audit.

### 6.6 Trust scoring
Score = weighted combination of transparent subscores (domain tier, https, authorship, dated,
citation of primary sources, content-quality heuristics), user-editable domain tiers on top.

- **Limit:** it measures *signals associated with reliability*, not accuracy of a given article.
  Weights are heuristic until calibrated against a labeled set (Roadmap Phase 4).

### 6.7 Confidence
Per statement, in `[0, 1]`:

```
support  = Σ trust_i  over independent supporting sources   (diminishing returns per source)
dissent  = Σ trust_j  over independent dissenting sources
confidence = support / (support + dissent + k)        # k = prior, shrinks confidence with few sources
```

It is an **evidence-balance indicator, not a probability**. A single high-trust source stays
visibly below a multi-source consensus. The README says so explicitly.

### 6.8 Language support
Turkish and English are first-class from day one. The tokenizer uses Unicode word characters
(`\w` with `re.UNICODE` plus `unicodedata` normalization), never `[a-z0-9]`, and Turkish casing
is handled (`İ/ı`). Stop-word lists live in data files per language, selected by detected
language (simple script + stop-word-frequency detector, no dependency).

### 6.9 Storage and audit
One SQLite file in a private app directory. Tables: `runs`, `pages`, `documents`, `claims`,
`relations`, `statements`, `tiers`, `cache_index`.

- Keep the DB under `$HOME`/app data, **not** on shared storage (`/sdcard`): SQLite locking
  and permissions are unreliable there.
- `storage.db` is a context manager; connections are always closed.

### 6.10 AI Agent layer (later, still not an LLM)
An agent is **planner + tools + budget + stop rule**:

- Tools: `search`, `fetch`, `extract_claims`, `score_source`, `compare`, `expand_query`.
- Planner is a deterministic state machine: initial search → read top sources → if
  contradictions or too few independent sources → targeted follow-up queries → stop on
  budget, coverage or diminishing returns.
- Every step is logged to the audit trail. The agent lives behind the same pipeline
  interfaces, so it adds no new dependencies.

## 7. Cross-platform strategy (Android Termux / Linux / Windows)

- `pathlib` everywhere; one `paths.py` resolves data/cache/config dirs
  (`XDG_*` on Linux, `%APPDATA%` on Windows, `$HOME/.local/share` under Termux).
- Explicit `encoding="utf-8"` on every file open; at startup reconfigure `stdout`/`stderr` to
  UTF-8 with `errors="replace"` so Windows consoles do not crash on characters like "—".
- No `fork`, signals, symlinks or POSIX-only calls. Concurrency via threads for I/O.
- TLS: rely on the system trust store; Termux requires the `ca-certificates` package.
- CI matrix (later): Linux, Windows, and a Termux smoke test script.

## 8. Network safety and etiquette

- Allow only `http`/`https`; resolve and **block private/loopback/link-local IP ranges** for
  user-supplied URLs (SSRF guard); cap redirects.
- Hard limits on bytes, time, and content type; decompression-bomb guard.
- Respect `robots.txt`; per-domain rate limit; honest User-Agent.
- No JavaScript rendering, no login or paywall circumvention.

## 9. Testing strategy

- `unittest` (stdlib) by default; adopting `pytest` requires approval.
- Unit tests for every pure stage; table-driven relation tests (claim pairs with expected kind
  and signals); golden JSON output tests; offline HTML fixtures; Turkish and English cases in
  every text-processing suite.
- A small **evaluation set** of labeled claim pairs to measure precision/recall of relation
  classification, so changing thresholds is measurable, not guesswork.

## 10. Known limitations

1. No semantic understanding: synonyms, paraphrase, implication and sarcasm are not handled.
2. Contradiction detection covers numbers, dates and explicit negation only.
3. Claim extraction from messy HTML is imperfect; boilerplate can leak in.
4. JS-rendered pages and paywalled pages are unreadable.
5. Search quality depends on the chosen provider.
6. Trust scores are heuristic and can be wrong for novel or niche sources.
7. Independence detection cannot see hidden common sourcing.
8. Confidence is not probability and says nothing about ground truth.
9. Pure-Python parsing is slower than native libraries.

## 11. Decisions taken

1. Search providers: user URLs (always), Wikipedia (default, no key), SearxNG (self-hosted),
   Brave (API key). No search-engine scraping.
2. Test runner: `unittest` (stdlib).
3. Packaging: `pyproject.toml`, `src/` layout, console script `dai`; also `run_dai.py`.
4. Output language: `auto` (follows the question language), English and Turkish strings.
5. The earlier prototype was rewritten inside this structure (Appendix A lists what was fixed).

---

## Appendix A: Review of the earlier prototype (`render.py`, `relations.py`, `cli.py`)

**Status: every item below is fixed in the rewrite**, and the regression-prone ones have tests
(negation vs high overlap, Turkish letters, empty subject, unit normalisation, `None`-safe rendering,
connection closing, exit codes, UTF-8 output).

These were produced before the architecture existed, contrary to the "design first" rule.
They also import modules that were not provided (`claims.segment`, `core.pipeline`,
`ingest.fetch`, `trust.score`, `agents.planner`, `config`, `extract.html_extract`), so they
cannot run alone. They are treated as a **reference prototype**: useful ideas, to be rewritten
inside the structure above after approval. Findings:

### relations.py
| # | Severity | Issue | Fix in new design |
|---|---|---|---|
| 1 | High | Tokenizer `[a-z0-9']+` drops Turkish letters (`için` becomes `i`, `n`), breaking Turkish analysis | Unicode-aware tokenizer in `i18n/tokenize.py` |
| 2 | High | Agreement rule (`j >= AGREE_J`) runs before negation rule; a long sentence with one added "not" can be classed as agreement | Conflict rules first (6.4) |
| 3 | Medium | Clustering is greedy and order-dependent, compares only to the first claim of each cluster | Deterministic sort then single-link or best-match assignment |
| 4 | Medium | Empty subject yields key `"\|predicate"`, merging unrelated claims | Skip key-based merge when subject is empty |
| 5 | Medium | Identical text from the same domain counts as agreement from independent sources | Independence stage (6.5) |
| 6 | Low | `tol` parameter in `numbers_differ` unused; `"the"` duplicated in `STOPWORDS`; thresholds hard-coded | Config-driven thresholds, per-language stop-word files |
| 7 | Low | Numbers mismatch of unit-bearing values ("5 km" vs "5000 m") not normalized | `claims/normalize.py` unit handling |

### render.py
| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | High | `ev.quote[:120]` and `ev.trust:.0f` crash when quote or trust is `None` | Defensive formatting |
| 2 | Medium | Reference-registry logic duplicated in `render_json` and `render_text` | Shared `render/refs.py` |
| 3 | Medium | Confidence printed as `%` but scale is undefined; trust uses 0-100 | One `[0,1]` scale, formatted at render time |
| 4 | Low | `"..."` appended even when the quote is shorter than 120 chars; only first dissent shown | Truncate with ellipsis only when cut; show all or count |
| 5 | Low | URLs not canonicalized (`utm_*`, trailing slash) so one page can get two reference numbers | Canonical URL function |
| 6 | Low | `chr(10).join(lines)`; stats not shown in text output | Plain `"\n".join`, optional stats footer |

### cli.py
| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | High | `db.close()` not in `finally`; exception leaks connection | `with` context manager |
| 2 | High | Printing non-ASCII on Windows consoles can crash | UTF-8 stdout reconfigure (section 7) |
| 3 | Medium | No `if __name__ == "__main__": sys.exit(main())`; unclear entry point | `__main__.py` plus console script |
| 4 | Medium | `--url` silently ignored when `--agent` is set; `--max-sources 0` treated as unset | Validate flag combinations; compare against `None` |
| 5 | Medium | `research` returns exit code 0 even when every source failed | Non-zero exit when no usable evidence |
| 6 | Low | `build_parser()` called twice; manual tier validation and domain-required check instead of argparse | Subparsers per action with `choices` |
| 7 | Low | Domains not normalized (`WWW.Example.com`) in `sources add/remove` | Normalize in `trust/tiers.py` |
| 8 | Low | Repeated fetch/extract boilerplate in `fetch`, `claims`, `trust` commands | Shared helper in `cli/commands/_common.py` |

---

## Appendix B: Implementation notes, deviations and unverified areas

Deviations from the original proposal:

- Domain tiers and stop-word lists are Python modules, not data files (no package-data problems
  when the project is copied around on Termux or unzipped).
- Claim typing lives in `claims/segment.py`; there is no separate `typing.py`.
- SQLite holds `pages`, `tiers`, `runs`; claims, clusters and relations are stored inside each
  run's JSON trace instead of their own tables.
- Number extraction records **context markers** per number (unit class, `@pct`, `@cur`, neighbouring
  stems) so that only numbers describing the same quantity can contradict each other.
- Relation rules gained two refinements found by testing: a claim that merely adds detail
  (extra numbers) is *compatible*, not a conflict; a *date as the only differing value* is a
  contradiction, while differing numbers plus differing dates is an *update*.
- Clustering also groups claims that share a numeric context (needed for Turkish, where nouns are
  not capitalised and so are not detected as entities).

Not verified yet (be aware before relying on them):

- **Live web.** The build environment had no internet access. The fetcher, robots.txt, redirects,
  size limits, gzip handling and the SearxNG provider were tested against a local HTTP server; the
  Wikipedia and Brave providers were tested only against mocked JSON.
- **Platforms.** Tests ran on Linux with Python 3.12.3. Termux, Windows and Python 3.13 were not
  exercised (the code uses only standard-library features available since 3.11).
- **Quality on real pages.** Extraction, claim typing and relation rules are heuristics tuned on
  synthetic English and Turkish fixtures. Expect misses and false positives on real sites; the
  `claims`, `trust` and `audit --format trace` commands exist to inspect exactly why.
- Trust weights, thresholds and confidence prior are uncalibrated defaults.
