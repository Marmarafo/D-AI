"""Source independence: collapse copies, syndication and shared wire sourcing."""
from __future__ import annotations

import re

from ..core.models import Document
from ..i18n.tokenize import jaccard, tokens
from ..ingest.urls import registered_domain

WIRES = {
    "reuters": ("reuters",), "ap": ("associated press", "ap"), "afp": ("afp",),
    "aa": ("anadolu ajansı", "anadolu ajansi", "anadolu agency", "aa"),
    "dha": ("dha", "demirören haber ajansı"), "iha": ("iha", "ihlas haber ajansı"),
    "dpa": ("dpa",), "xinhua": ("xinhua",), "upi": ("upi",), "tass": ("tass",),
}
WIRE_DOMAINS = {"reuters.com": "reuters", "apnews.com": "ap", "afp.com": "afp",
                "aa.com.tr": "aa", "dha.com.tr": "dha", "iha.com.tr": "iha",
                "xinhua.net": "xinhua", "upi.com": "upi", "tass.com": "tass"}
_ALIAS = {a: w for w, al in WIRES.items() for a in al}
_NAMES = "|".join(sorted((re.escape(a) for a in _ALIAS), key=len, reverse=True))
_CREDIT = re.compile(rf"(?i)(?:\(\s*({_NAMES})\s*\)|\b({_NAMES})\s*[-—–]\s|[-—–]\s*({_NAMES})\b)")
_ATTRIB = re.compile(rf"(?i)\b(?:according to|reported by|via|kaynak:?|göre)\s+({_NAMES})\b")
_ATTRIB2 = re.compile(rf"(?i)\b({_NAMES})\s+(?:reported|said|reports|bildirdi|duyurdu)\b")


def wire_tags(doc: Document) -> set[str]:
    tags: set[str] = set()
    dom = doc.domain
    if dom in WIRE_DOMAINS:
        tags.add(WIRE_DOMAINS[dom])
    for m in _CREDIT.finditer(doc.text[:300]):
        name = next(g for g in m.groups() if g)
        tags.add(_ALIAS[name.lower()])
    for rx in (_ATTRIB, _ATTRIB2):
        for m in rx.finditer(doc.text):
            tags.add(_ALIAS[m.group(1).lower()])
    return tags


def _shingles(text: str, n: int = 5, limit: int = 1500) -> frozenset:
    t = tokens(text)[:limit]
    if len(t) < n:
        return frozenset([" ".join(t)]) if t else frozenset()
    return frozenset(" ".join(t[i:i + n]) for i in range(len(t) - n + 1))


def group_documents(docs: list[Document], dup_j: float = 0.5) -> dict[str, int]:
    """Map document url -> independence group id (documents in one group count once)."""
    n = len(docs)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    sh = [_shingles(d.text) for d in docs]
    tags = [wire_tags(d) for d in docs]
    doms = [registered_domain(d.domain) or d.domain for d in docs]
    for i in range(n):
        for j in range(i + 1, n):
            if doms[i] == doms[j] or (tags[i] & tags[j]) or jaccard(sh[i], sh[j]) >= dup_j:
                union(i, j)
    return {docs[i].url: find(i) for i in range(n)}
