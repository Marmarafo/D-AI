# D-AI (DevelopperS Artificial Intelligence), generation 1

An **algorithmic** research assistant. D-AI reads several web sources, extracts claims, scores
how reliable each source looks, finds where sources agree or contradict, collapses copied
sources, and answers with every statement tied to a **quote and URL**.

**D-AI is not a language model.** It never writes free text of its own: every answer sentence is a
sentence taken from a source, with its evidence attached.

- Python standard library only (no `pip install` needed), pure Python, works on Android (Termux),
  Linux and Windows
- English and Turkish are both first-class (Turkish letters, `İ/ı`, apostrophe suffixes, `-ma/-me`
  negation, `1.234,5` numbers)
- Every score, relation and confidence value carries the signals behind it; every run is stored and
  can be re-rendered offline (`dai audit`)
- D-AI 2.0 is a separate future generation and is out of scope

## Quick start

```
python run_dai.py research "How tall is the Marlow Tower?" \
    --url https://example.org/a --url https://example.org/b
```

No `--url`? D-AI asks the configured search providers (default: Wikipedia, no key needed):

```
python run_dai.py research "Türkiye'nin nüfusu kaç?"
python run_dai.py research "What is the population of Norway?" --agent --json
```

Optional install (needs setuptools, which `pip` fetches itself): `pip install -e .` then use `dai ...`.

### Termux (Android)

```
pkg install python ca-certificates
cd D-AI
python run_dai.py research "..." --url https://...
```

Data lives under `~/.local/share/dai` (inside Termux's private storage). Do **not** point
`DAI_HOME`/`db_path` at `/sdcard`: SQLite locking is unreliable there (D-AI warns you).

## Commands

| Command | What it does |
|---|---|
| `research QUESTION [--url U]... [--agent] [--json] [--offline] [--lang en\|tr] [--providers a,b] [--max-sources N] [--trace]` | full pipeline; exit code 3 if no supported statement was found |
| `fetch URL...` | fetch + extract article text and metadata |
| `claims URL...` | show extracted claims (type, subject, predicate, numbers, dates, negation) |
| `trust URL...` | explainable source score with sub-scores and signals |
| `sources list \| add DOMAIN tier1\|tier2\|tier3 \| remove DOMAIN` | edit reputation tiers |
| `audit RUN_ID [--format summary\|text\|json\|trace]` | inspect or re-render a stored run (offline) |
| `runs`, `cache stats\|clear`, `config` | housekeeping |

`--agent` runs the deterministic research agent: search, read, analyse, and if there are too few
independent sources or sources disagree, run follow-up searches (bounded rounds and source budget).
Every step is logged in the audit trace. It is a planner + tools + stop rule, **not** an LLM.

## How an answer is built

```
question → discover (providers / --url) → fetch (robots.txt, rate limit, cache, SSRF guard)
→ extract (main text + metadata) → claims (sentences, type, numbers, dates, negation)
→ relevance filter → trust score → cluster + relation rules → independence groups
→ statements with supporting evidence and dissent → JSON + text  → stored in SQLite
```

Relations are decided by ordered, explainable rules: identical text, negation in exactly one
claim, different dates (an *update*, e.g. a time series), a numeric mismatch in the same quantity
slot (unit-normalised: `5 km` = `5000 m`), otherwise overlap-based agreement or nuance.

Sample (three pages on one host count as one independent source, hence "disputed"):

```
Q: How tall is the Marlow Tower?

1. (38%, disputed) The Marlow Tower is 320 metres tall and was completed in 2019. [1],[2]
   disputed by: "The Marlow Tower is 305 metres tall, local media wrote." [3]
...
Confidence is an evidence-balance indicator, not a probability of truth.
```

## Configuration

`dai config` prints the effective settings and the database path. Copy `config.example.toml` to the
data directory as `config.toml`. Precedence: defaults < file < `DAI_<KEY>` environment variables <
command-line flags. Search providers: `wikipedia` (no key), `searxng` (set `searxng_url`),
`brave` (set `BRAVE_API_KEY`). Scraping search-engine result pages is deliberately not included.

The default domain tiers (`trust/tiers.py`) are an editable convenience, not an endorsement or
ranking of outlets. Adjust them with `dai sources add`.

## Honest limitations

- Answers mean "supported by these sources", **not** "true".
- Matching is lexical, not semantic: heavily paraphrased claims can be missed, synonyms are not
  understood, and claims in different languages are not compared with each other.
- Contradictions are found through numbers, dates and explicit negation only.
- Confidence is an evidence-balance indicator, **not** a probability.
- Trust scores are heuristic and measure signals associated with reliability, not whether a given
  article is correct. Weights have not been calibrated against a labelled set.
- Independence detection is heuristic: same domain, near-duplicate text, shared wire credit.
  Pages that share large boilerplate can be merged (this errs towards under-counting).
- JavaScript-rendered pages, paywalls, PDFs and login walls are not supported.
- Claim extraction from messy HTML is imperfect; Turkish stemming is a 5-character prefix.
- The SSRF guard resolves the host before fetching, but urllib resolves again when connecting
  (DNS rebinding is not fully closed).
- Search quality depends on the provider you configure.

## Tests

```
python run_tests.py        # 69 offline tests, no network required
```

## Layout

See `ARCHITECTURE.md` (design, decisions, limitations, review of the earlier prototype) and
`ROADMAP.md` (phases and status).

## License

Not chosen yet. Decide before sharing the code publicly.
