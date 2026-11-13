"""Pairwise claim relation classification (lexical + structural, fully explainable).

Rules run in a fixed order; the first that fires wins and its signals are recorded.
Conflict rules come BEFORE the "high overlap = agreement" shortcut.
"""
from __future__ import annotations

import math

from ..claims.normalize import dates_incompatible
from ..core.models import Claim, Relation
from ..i18n.tokenize import jaccard


def _close(x: float, y: float, rel_tol: float) -> bool:
    return math.isclose(x, y, rel_tol=rel_tol, abs_tol=1e-9)


def numeric_conflict(a: Claim, b: Claim, rel_tol: float, j: float, num_j: float):
    """Return (state, detail). state: 'none' | 'equal' | 'compatible' | 'conflict'."""
    if not a.numbers or not b.numbers:
        return "none", None
    ua = [(v, c) for v, c in zip(a.numbers, a.num_ctx)
          if not any(_close(v, w, rel_tol) for w in b.numbers)]
    ub = [(w, c) for w, c in zip(b.numbers, b.num_ctx)
          if not any(_close(w, v, rel_tol) for v in a.numbers)]
    if not ua and not ub:
        return "equal", None
    if not ua or not ub:
        return "compatible", None     # one claim is a more detailed version of the other
    for v, cv in ua:
        for w, cw in ub:
            shared = cv & cw
            if shared:
                return "conflict", f"{v:g} vs {w:g} (shared context: {sorted(shared)})"
    if j >= max(0.5, num_j) and len(ua) == 1 and len(ub) == 1:
        return "conflict", f"{ua[0][0]:g} vs {ub[0][0]:g} (high text overlap)"
    return "compatible", None


def classify_pair(a: Claim, b: Claim, cfg) -> Relation:
    j = jaccard(a.stems, b.stems)
    ents = a.entities & b.entities
    sig = [f"jaccard={j:.2f}"]
    if ents:
        sig.append(f"shared entities: {sorted(ents)[:4]}")
    if a.normalized == b.normalized:
        return Relation(kind="agreement", signals=sig + ["identical text"])
    if j < 0.20 and not ents:
        return Relation(kind="unrelated", signals=sig)

    state, detail = numeric_conflict(a, b, cfg.num_rel_tol, j, cfg.num_j)

    if a.negated != b.negated and j >= cfg.neg_j:
        if state == "conflict":
            return Relation(kind="nuance", signals=sig + ["negation differs, numbers also differ"])
        return Relation(kind="contradiction", signals=sig + ["negation cue in exactly one claim"])

    if dates_incompatible(a.dates, b.dates) and j >= cfg.overlap_j:
        diff = f"dates differ: {sorted(a.dates)} vs {sorted(b.dates)}"
        if a.numbers and b.numbers:
            return Relation(kind="update", signals=sig + [diff, "same fact at a different time"])
        if j >= cfg.num_j:
            return Relation(kind="contradiction", signals=sig + [diff, "date is the differing value"])
        return Relation(kind="nuance", signals=sig + [diff])

    if state == "conflict" and (j >= 0.25 or ents):
        return Relation(kind="contradiction", signals=sig + [f"numeric mismatch: {detail}"])

    if j >= cfg.agree_j:
        return Relation(kind="agreement", signals=sig + ["high lexical overlap"])
    if state == "equal" and j >= cfg.overlap_j and (ents or j >= 0.5):
        return Relation(kind="agreement",
                        signals=sig + ["same numbers, shared subject matter, no conflict signal"])
    if j >= cfg.overlap_j:
        return Relation(kind="nuance", signals=sig + ["partial overlap, no conflict signal"])
    return Relation(kind="unrelated", signals=sig)
