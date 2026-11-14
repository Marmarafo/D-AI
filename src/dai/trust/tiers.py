"""Editable domain reputation tiers.

IMPORTANT: these defaults are a convenience, not an endorsement or a ranking of outlets.
tier1 = wire agencies, intergovernmental bodies, scientific institutions, government/education
domains; tier2 = established general media/reference; tier3 = user-generated or low-reliability
platforms. Anything else is "unrated". Override with `dai sources add DOMAIN TIER`.
"""
from __future__ import annotations

from ..ingest.urls import registered_domain

TIER_VALUES = {"tier1": 0.95, "tier2": 0.75, "unrated": 0.45, "tier3": 0.15}

DEFAULT_TIERS = {
    # tier1
    "reuters.com": "tier1", "apnews.com": "tier1", "aa.com.tr": "tier1", "afp.com": "tier1",
    "who.int": "tier1", "un.org": "tier1", "nature.com": "tier1", "science.org": "tier1",
    "nih.gov": "tier1", "cdc.gov": "tier1", "nasa.gov": "tier1", "europa.eu": "tier1",
    "worldbank.org": "tier1", "imf.org": "tier1", "oecd.org": "tier1", "who.org": "tier1",
    # tier2
    "bbc.com": "tier2", "bbc.co.uk": "tier2", "nytimes.com": "tier2", "theguardian.com": "tier2",
    "washingtonpost.com": "tier2", "wsj.com": "tier2", "ft.com": "tier2", "economist.com": "tier2",
    "bloomberg.com": "tier2", "dw.com": "tier2", "aljazeera.com": "tier2", "france24.com": "tier2",
    "britannica.com": "tier2", "wikipedia.org": "tier2", "trthaber.com": "tier2",
    "hurriyet.com.tr": "tier2", "milliyet.com.tr": "tier2", "sabah.com.tr": "tier2",
    "haberturk.com": "tier2", "ntv.com.tr": "tier2", "cnnturk.com": "tier2",
    "sozcu.com.tr": "tier2", "cumhuriyet.com.tr": "tier2", "bianet.org": "tier2",
    "dunya.com": "tier2", "bloomberght.com": "tier2",
    # tier3
    "reddit.com": "tier3", "quora.com": "tier3", "medium.com": "tier3", "blogspot.com": "tier3",
    "wordpress.com": "tier3", "tumblr.com": "tier3", "facebook.com": "tier3", "x.com": "tier3",
    "twitter.com": "tier3", "instagram.com": "tier3", "tiktok.com": "tier3",
    "pinterest.com": "tier3", "eksisozluk.com": "tier3", "uludagsozluk.com": "tier3",
    "youtube.com": "tier3",
}
_TLD_TIER1 = (".gov", ".edu", ".mil", ".int", ".gov.tr", ".edu.tr", ".gov.uk", ".ac.uk",
              ".gov.au", ".edu.au", ".gc.ca", ".k12.tr", ".bel.tr")


def _candidates(host: str):
    labels = host.lower().strip(".").split(".")
    for i in range(len(labels) - 1):
        yield ".".join(labels[i:])


def lookup_tier(host: str, user_map: dict | None = None) -> tuple[str, str]:
    """Return (tier, source) where source is 'user', 'default', 'tld' or 'none'."""
    user_map = user_map or {}
    for cand in _candidates(host):
        if cand in user_map:
            return user_map[cand], "user"
    for cand in _candidates(host):
        if cand in DEFAULT_TIERS:
            return DEFAULT_TIERS[cand], "default"
    h = host.lower()
    if any(h.endswith(t) for t in _TLD_TIER1):
        return "tier1", "tld"
    return "unrated", "none"


def normalize_domain(d: str) -> str:
    d = d.strip().lower()
    for pre in ("https://", "http://"):
        if d.startswith(pre):
            d = d[len(pre):]
    d = d.split("/")[0].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d
