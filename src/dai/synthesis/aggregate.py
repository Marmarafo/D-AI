"""Turn clusters + relations into ranked statements with supporting/dissenting evidence."""
from __future__ import annotations

from ..core.models import Claim, Document, Evidence, Statement, TrustReport
from .confidence import confidence, status
from .strength import evidence_strength


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


def _evidence(c: Claim, rep: Claim, docs: dict, trust: dict, profile=None) -> Evidence:
    d = docs[c.doc_url]
    s, sig = evidence_strength(c, rep, profile)
    return Evidence(url=c.doc_url, domain=d.domain, title=d.title, quote=c.text,
                    reliability=trust[c.doc_url].score, strength=s, strength_signals=sig,
                    published=d.published, claim_type=c.claim_type)


def _best_per_doc(idx: list[int], claims: list[Claim], docs, trust, rep: Claim,
                  profile=None) -> list[Evidence]:
    best: dict[str, Claim] = {}
    for i in idx:
        c = claims[i]
        cur = best.get(c.doc_url)
        if cur is None or (c.relevance, -c.start) > (cur.relevance, -cur.start):
            best[c.doc_url] = c
    ev = [_evidence(c, rep, docs, trust, profile) for c in best.values()]
    ev.sort(key=lambda e: (-e.reliability, -e.strength, e.url))
    return ev


def _group_trusts(idx, claims, trust, groups) -> dict[int, float]:
    out: dict[int, float] = {}
    for i in idx:
        u = claims[i].doc_url
        g = groups[u]
        out[g] = max(out.get(g, 0.0), trust[u].score)
    return out


def synthesize(claims: list[Claim], clusters, docs: dict[str, Document],
               trust: dict[str, TrustReport], groups: dict[str, int], cfg,
               profile=None) -> list[Statement]:
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
            if r.kind == "agreement":
                for s in r.signals:
                    if s.startswith("approximate numeric match: "):
                        notes_by[ra].append(("approx", s.split(": ", 1)[1]))
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
            dis_rep = (max((claims[i] for i in dis_idx),
                           key=lambda c: (c.relevance, trust[c.doc_url].score, -c.start))
                       if dis_idx else rep)
            notes = list(dict.fromkeys(notes_by[root]))
            if nuance_count[root]:
                notes.append(("nuance", str(nuance_count[root])))
            docs_in = {claims[i].doc_url for i in idx}
            if len(docs_in) > len(sup):          # several documents, fewer independent sources
                notes.append(("copies", str(len(docs_in)), str(len(sup))))
            st = Statement(
                text=rep.text, claim_type=rep.claim_type, balance=round(conf, 4),
                relevance=round(rep.relevance, 4),
                status=status(len(sup), list(sup.values()), list(dis.values()), cfg.conf_decay),
                cluster_size=len(mem), independent_sources=len(sup),
                supporting=tuple(_best_per_doc(idx, claims, docs, trust, rep, profile)),
                dissent=(tuple(_best_per_doc(dis_idx, claims, docs, trust, dis_rep, profile))
                         if dis_idx else ()),
                notes=tuple(notes))
            # ranking only: balance stays a pure support-vs-dissent measure; strength and
            # relevance decide which statements answer the question best
            best_strength = max((e.strength for e in st.supporting), default=0.0)
            out.append((conf * max(rep.relevance, 0.01) * (0.5 + 0.5 * best_strength), st))
    out.sort(key=lambda t: (-t[0], t[1].text))
    return [s for _, s in out[:cfg.max_statements]]
