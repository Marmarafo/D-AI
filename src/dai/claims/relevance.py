"""Question relevance: how many of the question's content terms a claim covers."""
from __future__ import annotations

import math
from dataclasses import replace

from ..core.models import Claim
from ..i18n.tokenize import content_stems


def question_terms(question: str, lang: str) -> frozenset:
    return content_stems(question, lang)


def required_terms(n_terms: int, min_relevance: float) -> int:
    if n_terms <= 1:
        return n_terms
    return min(n_terms, max(2, math.ceil(min_relevance * n_terms)))


def score_claims(claims: list[Claim], terms: frozenset, min_relevance: float) -> list[Claim]:
    """Return relevant claims (relevance in [0,1]); empty question terms keep everything."""
    if not terms:
        return [replace(c, relevance=1.0) for c in claims]
    need = required_terms(len(terms), min_relevance)
    out = []
    for c in claims:
        hit = len(terms & c.stems)
        if hit >= need and hit > 0:
            out.append(replace(c, relevance=hit / len(terms)))
    return out
