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


def answer_factor(c: Claim, profile) -> tuple[float, str] | None:
    """How well the claim has the shape the question asks for (None: question has no shape)."""
    if profile is None or profile.kind == "open":
        return None
    if profile.kind == "date":
        ok = bool(c.dates)
        return (1.0 if ok else 0.6), f"asks for a date; claim {'has' if ok else 'has no'} one"
    has_num = bool(c.numbers)
    marker = profile.unit_marker
    unit_ok = marker is None or any(marker in ctx for ctx in c.num_ctx)
    ok = has_num and unit_ok
    what = f"a {profile.unit or 'number'} value"
    return (1.0 if ok else 0.6), f"asks for {what}; claim {'has' if ok else 'has no'} one"


def evidence_strength(c: Claim, rep: Claim, profile=None) -> tuple[float, tuple]:
    """Return (strength in 0..1, signals)."""
    type_f = TYPE_FACTOR.get(c.claim_type, 0.5)
    rel = 0.5 + 0.5 * max(0.0, min(1.0, c.relevance))
    sim = 1.0 if c is rep or c.normalized == rep.normalized else jaccard(c.stems, rep.stems)
    close = 0.5 + 0.5 * sim
    s = type_f * rel * close
    sig = (f"claim type {c.claim_type}: x{type_f:g}",
           f"question relevance {c.relevance:.2f}: x{rel:.2f}",
           f"closeness to position text {sim:.2f}: x{close:.2f}")
    af = answer_factor(c, profile)
    if af is not None:
        s *= af[0]
        sig += (f"{af[1]}: x{af[0]:g}",)
    return round(s, 4), sig
