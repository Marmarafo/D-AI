"""Evidence-balance confidence (NOT a probability)."""
from __future__ import annotations


def weighted_sum(trusts: list[float], decay: float) -> float:
    """Diminishing returns: the i-th strongest independent source counts decay**i."""
    return sum(t * decay ** i for i, t in enumerate(sorted(trusts, reverse=True)))


def confidence(support: list[float], dissent: list[float], prior: float, decay: float) -> float:
    s = weighted_sum(support, decay)
    d = weighted_sum(dissent, decay)
    return s / (s + d + prior) if (s + d + prior) > 0 else 0.0


def status(n_support_groups: int, support: list[float], dissent: list[float], decay: float) -> str:
    if dissent:
        s, d = weighted_sum(support, decay), weighted_sum(dissent, decay)
        return "disputed" if d >= 0.5 * s else "mixed"
    return "corroborated" if n_support_groups >= 2 else "single-source"
