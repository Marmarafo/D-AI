"""Turn clusters + relations into ranked statements with supporting/dissenting evidence."""
from __future__ import annotations

from ..core.models import Claim, Document, Evidence, Statement, TrustReport
from .confidence import confidence, status


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _evidence(c: Claim, docs: dict, trust: dict) -> Evidence:
    d = docs[c.doc_url]
    return Evidence(url=c.doc_url, domain=d.domain, title=d.title, quote=c.text,
                    trust=trust[c.doc_url].score, published=d.published, claim_type=c.claim_type)


def _best_per_doc(idx: list[int], claims: list[Claim], docs, trust) -> list[Evidence]:
    best: dict[str, Claim] = {}
    for i in idx:
        c = claims[i]
        cur = best.get(c.doc_url)
        if cur is None or (c.relevance, -c.start) > (cur.relevance, -cur.start):
            best[c.doc_url] = c
    ev = [_evidence(c, docs, trust) for c in best.values()]
    ev.sort(key=lambda e: (-e.trust, e.url))
    return ev


def _group_trusts(idx, claims, trust, groups) -> dict[int, float]:
    out: dict[int, float] = {}
    for i in idx:
        u = claims[i].doc_url
        g = groups[u]
        out[g] = max(out.get(g, 0.0), trust[u].score)
    return out


def synthesize(claims: list[Claim], clusters, docs: dict[str, Document],
               trust: dict[str, TrustReport], groups: dict[str, int], cfg) -> list[Statement]:
    out: list[tuple[float, Statement]] = []
    for cl in clusters:
        mem = cl.members
        uf = _UF(len(claims))
        for r in cl.relations:
            if r.kind == "agreement":
                uf.union(r.a, r.b)
        positions: dict[int, list[int]] = {}
        for i in mem:
            positions.setdefault(uf.find(i), []).append(i)
        conflicts: dict[int, set[int]] = {k: set() for k in positions}
        notes_by: dict[int, list] = {k: [] for k in positions}
        nuance_count: dict[int, int] = {k: 0 for k in positions}
        for r in cl.relations:
            ra, rb = uf.find(r.a), uf.find(r.b)
            if r.kind == "contradiction" and ra != rb:
                conflicts[ra].add(rb)
                conflicts[rb].add(ra)
            elif r.kind == "update" and ra != rb:
                for me, other in ((ra, r.b), (rb, r.a)):
                    oc = claims[other]
                    notes_by[me].append(("update", docs[oc.doc_url].domain, ",".join(oc.dates)))
            elif r.kind == "nuance":
                nuance_count[ra] += 1
                if rb != ra:
                    nuance_count[rb] += 1
        for root, idx in positions.items():
            sup = _group_trusts(idx, claims, trust, groups)
            dis_idx = [i for o in sorted(conflicts[root]) for i in positions[o]]
            dis = _group_trusts(dis_idx, claims, trust, groups) if dis_idx else {}
            conf = confidence(list(sup.values()), list(dis.values()), cfg.conf_prior, cfg.conf_decay)
            rep = max((claims[i] for i in idx),
                      key=lambda c: (c.relevance, trust[c.doc_url].score, -c.start))
            notes = list(dict.fromkeys(notes_by[root]))
            if nuance_count[root]:
                notes.append(("nuance", str(nuance_count[root])))
            st = Statement(
                text=rep.text, claim_type=rep.claim_type, confidence=round(conf, 4),
                relevance=round(rep.relevance, 4),
                status=status(len(sup), list(sup.values()), list(dis.values()), cfg.conf_decay),
                cluster_size=len(mem), independent_sources=len(sup),
                supporting=tuple(_best_per_doc(idx, claims, docs, trust)),
                dissent=tuple(_best_per_doc(dis_idx, claims, docs, trust)) if dis_idx else (),
                notes=tuple(notes))
            out.append((conf * max(rep.relevance, 0.01), st))
    out.sort(key=lambda t: (-t[0], t[1].text))
    return [s for _, s in out[:cfg.max_statements]]
