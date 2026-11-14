"""Evidence strength: how strongly ONE source's claim supports ONE position.

This is deliberately separate from two other concepts:

* source reliability (trust/score.py): how much a *source* can be relied on in general;
* claim assessment (synthesis/confidence.py): what the combined evidence shows about the claim.

Strength looks only at the claim text versus the question and versus the position's
representative sentence. A highly reliable source that barely touches the question
is weak evidence; a modest source that states the claim directly is stronger evidence.
Heuristic and explainable, not calibrated.
"""
from __future__ import annotations

from ..core.models import Claim
from ..i18n.tokenize import jaccard

# Keys must cover every type classify_type() can return; unknown types fall back to 0.5.
TYPE_FACTOR = {"fact": 1.0, "statistic": 1.0, "quote": 0.7, "forecast": 0.4, "opinion": 0.3}


def evidence_strength(c: Claim, rep: Claim) -> tuple[float, tuple]:
    """Return (strength in 0..1, signals)."""
    type_f = TYPE_FACTOR.get(c.claim_type, 0.5)
    rel = 0.5 + 0.5 * max(0.0, min(1.0, c.relevance))
    sim = 1.0 if c is rep or c.normalized == rep.normalized else jaccard(c.stems, rep.stems)
    close = 0.5 + 0.5 * sim
    s = type_f * rel * close
    sig = (f"claim type {c.claim_type}: x{type_f:g}",
           f"question relevance {c.relevance:.2f}: x{rel:.2f}",
           f"closeness to position text {sim:.2f}: x{close:.2f}")
    return round(s, 4), sig
