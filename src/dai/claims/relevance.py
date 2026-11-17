"""Question relevance: does a claim help to answer the question?

Without a profile this is the original rule (how many of the question's content terms a claim
covers). With a profile (see question.py) it also checks the *shape* of the answer:

* a quantity question ("how tall", "kaç", "population") needs a sentence with a number, and for
  lengths/masses/prices the number must carry that kind of unit;
* a date question needs a sentence with a date;
* the document's title can stand in for the subject when the sentence itself does not repeat it
  ("The agreed height of 8,848.86 metres ..." inside an article titled "... Everest height");
* a number that sits next to a *different* name ("Mount K2, is only 8,611 meters") is demoted.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace

from ..core.models import Claim
from ..i18n.tokenize import content_stems, fold, stem, stopwords

TOPIC_CREDIT = 0.75        # share of an entity a matching document title is worth
DISTRACTOR_FACTOR = 0.6
YEAR_MISS_FACTOR = 0.7


def question_terms(question: str, lang: str) -> frozenset:
    return content_stems(question, lang)


def required_terms(n_terms: int, min_relevance: float) -> int:
    if n_terms <= 1:
        return n_terms
    return min(n_terms, max(2, math.ceil(min_relevance * n_terms)))


def _distractor(c: Claim, profile, lang: str) -> bool:
    """True when the first number follows a capitalised name that is not in the question."""
    if not profile.entity_stems or not c.numbers:
        return False
    m = re.search(r"\d", c.text)
    if not m:
        return False
    window = re.findall(r"[\w'’-]+", c.text[:m.start()])[-6:]
    sw = stopwords(lang)
    for w in window:
        base = w.split("'")[0].split("’")[0]
        if len(base) > 1 and base[0].isupper() and fold(base) not in sw \
                and stem(fold(base), lang) not in profile.entity_stems:
            return True
    return False


def _unit_ok(c: Claim, profile) -> bool:
    marker = profile.unit_marker
    if marker is None:
        return True
    return any(marker in ctx for ctx in c.num_ctx)


def _score_with_profile(c: Claim, terms: frozenset, need: int, profile, topic: frozenset,
                        lang: str) -> float | None:
    ents = profile.entity_stems
    core = terms - profile.function_stems - profile.prop_stems
    own = (len(ents & c.stems) / len(ents)) if ents else 0.0
    topic_hit = bool(ents & topic) if ents else False
    cov = max(own, TOPIC_CREDIT if topic_hit else 0.0)
    prop_hit = bool(profile.prop_stems & c.stems)

    if profile.kind == "quantity":
        if not c.numbers:
            return None
        if ents:
            if cov < 0.5:
                return None
        else:                                  # no names in the question ("world population")
            core = core or terms
            cov = len(core & c.stems) / len(core)
            if cov < 0.5 and not prop_hit:
                return None
        unit_ok = _unit_ok(c, profile)
        if not unit_ok:
            return None
        rel = 0.55 * cov + 0.30 * (1.0 if prop_hit else 0.0) + 0.15 * (1.0 if profile.unit_marker else 0.5)
        if _distractor(c, profile, lang):
            rel *= DISTRACTOR_FACTOR
    else:
        own_hits = len(terms & c.stems)
        topic_hits = len((terms & topic) - c.stems) if (topic and own_hits >= 1) else 0
        hit = own_hits + topic_hits
        if hit < need or hit == 0:
            return None
        rel = hit / len(terms)
        if profile.kind == "date":
            if not c.dates:
                return None
            rel = min(1.0, rel + 0.1)

    if profile.years:
        has_year = any(y in d for y in profile.years for d in c.dates) or \
            any(y in c.text for y in profile.years)
        rel = min(1.0, rel + 0.1) if has_year else rel * YEAR_MISS_FACTOR
    return max(0.01, min(1.0, rel))


def score_claims(claims: list[Claim], terms: frozenset, min_relevance: float,
                 profile=None, topics: dict | None = None, lang: str = "en") -> list[Claim]:
    """Return relevant claims (relevance in [0,1]); empty question terms keep everything."""
    if not terms:
        return [replace(c, relevance=1.0) for c in claims]
    need = required_terms(len(terms), min_relevance)
    out = []
    for c in claims:
        if profile is None:
            hit = len(terms & c.stems)
            if hit >= need and hit > 0:
                out.append(replace(c, relevance=hit / len(terms)))
            continue
        rel = _score_with_profile(c, terms, need, profile,
                                  (topics or {}).get(c.doc_url, frozenset()), lang)
        if rel is not None:
            out.append(replace(c, relevance=round(rel, 4)))
    return out
