"""Explainable source reliability score (heuristic, 0..1)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..core.models import Document, TrustReport
from ..ingest.urls import host_of
from .tiers import TIER_VALUES, lookup_tier

WEIGHTS = {"domain": 0.45, "https": 0.05, "authorship": 0.10, "dated": 0.10,
           "depth": 0.10, "citations": 0.10, "tone": 0.10}
_CLICKBAIT = re.compile(
    r"(?i)(you won'?t believe|shocking|mind-?blowing|this one trick|şok|inanamayacaksınız|"
    r"herkes bunu konuşuyor|bunu görünce)")


def score_source(url: str, doc: Document, user_tiers: dict | None = None) -> TrustReport:
    host = host_of(url)
    tier, src = lookup_tier(host, user_tiers)
    sub: dict[str, float] = {}
    sig: list[str] = []
    sub["domain"] = TIER_VALUES[tier]
    sig.append(f"domain {host}: {tier}" + (f" ({src})" if src != "none" else " (no rating)"))
    https = urlsplit(url).scheme == "https"
    sub["https"] = 1.0 if https else 0.3
    if not https:
        sig.append("not served over https")
    if doc.author:
        sub["authorship"] = 1.0
    elif doc.publisher:
        sub["authorship"] = 0.6
        sig.append("no author, publisher named")
    else:
        sub["authorship"] = 0.3
        sig.append("no author or publisher found")
    sub["dated"] = 1.0 if doc.published else 0.4
    if not doc.published:
        sig.append("no publication date found")
    wc = doc.word_count
    sub["depth"] = 0.2 if wc < 80 else 0.5 if wc < 200 else 0.8 if wc < 500 else 1.0
    if wc < 200:
        sig.append(f"short text ({wc} words)")
    n = doc.external_links
    sub["citations"] = 0.4 if n == 0 else 0.7 if n < 3 else 1.0
    title = doc.title or ""
    letters = [c for c in title if c.isalpha()]
    upper_ratio = sum(c.isupper() for c in letters) / len(letters) if letters else 0
    tone = 1.0
    if _CLICKBAIT.search(title) or title.count("!") >= 2 or (len(letters) > 12 and upper_ratio > 0.6):
        tone = 0.2
        sig.append("sensational title")
    elif doc.text.count("!") > max(3, doc.word_count // 60):
        tone = 0.5
        sig.append("many exclamation marks in text")
    sub["tone"] = tone
    score = sum(WEIGHTS[k] * sub[k] for k in WEIGHTS)
    return TrustReport(url=url, score=round(score, 4), tier=tier,
                       subscores={k: round(v, 3) for k, v in sub.items()}, signals=tuple(sig))
