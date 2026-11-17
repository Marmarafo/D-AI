"""Deterministic clustering of similar claims + within-cluster relation analysis."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.models import Claim, Relation
from ..i18n.tokenize import jaccard, overlap_coef
from .relations import classify_pair


@dataclass
class Cluster:
    key: str
    members: list = field(default_factory=list)      # claim indices
    relations: list = field(default_factory=list)    # Relation (indices into claims list)


def cluster_key(c: Claim) -> str:
    return " ".join(c.subject.split()[:4]) + "|" + c.predicate


def cluster_similarity(a: Claim, b: Claim, cluster_j: float) -> float:
    j = jaccard(a.stems, b.stems)
    ents = a.entities & b.entities
    shared_num = bool(set(a.numbers) & set(b.numbers))
    best = j
    if ents or shared_num:
        best = max(best, 0.85 * overlap_coef(a.stems, b.stems))
    if (ents and a.predicate and a.predicate == b.predicate and a.numbers and b.numbers
            and (j >= 0.20 or (len(ents) >= 2 and j >= 0.15))):
        best = max(best, cluster_j)      # a single shared name + "be" must not merge unrelated facts
    if a.numbers and b.numbers and j >= 0.25 and any(
            ca & cb for ca in a.num_ctx for cb in b.num_ctx):
        best = max(best, cluster_j)      # same quantity slot (e.g. both are about "nüfus")
    ka, kb = cluster_key(a), cluster_key(b)
    if a.subject and ka == kb and a.predicate:
        best = max(best, cluster_j)
    return best


def cluster_claims(claims: list[Claim], cfg) -> list[Cluster]:
    """Greedy best-match assignment; callers pass claims in a canonical order."""
    clusters: list[Cluster] = []
    for i, c in enumerate(claims):
        best, best_sim = None, 0.0
        for cl in clusters:
            sim = max(cluster_similarity(c, claims[m], cfg.cluster_j) for m in cl.members)
            if sim >= cfg.cluster_j and sim > best_sim:
                best, best_sim = cl, sim
        if best is None:
            clusters.append(Cluster(key=cluster_key(c), members=[i]))
        else:
            best.members.append(i)
    return clusters


def analyze(claims: list[Claim], cfg) -> list[Cluster]:
    clusters = cluster_claims(claims, cfg)
    for cl in clusters:
        for x in range(len(cl.members)):
            for y in range(x + 1, len(cl.members)):
                ia, ib = cl.members[x], cl.members[y]
                r = classify_pair(claims[ia], claims[ib], cfg)
                r.a, r.b = ia, ib
                cl.relations.append(r)
    return clusters
