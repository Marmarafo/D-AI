"""Unicode-aware tokenization, folding, stemming, language detection.

Turkish needs care: ``İ/I/ı`` fold to ``i`` so that "Istanbul", "İstanbul" and
"istanbul" match, and apostrophe suffixes ("Türkiye'nin") are removed.
"""
from __future__ import annotations

import re
import unicodedata

from .stopwords import EN_STOP, NEG_EN, NEG_TR, TR_NEG_EXCEPTIONS, TR_STOP

_WORD_RE = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)
_TR_CHARS = set("çğışöüÇĞİŞÖÜ")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("İ", "i").replace("I", "i").replace("ı", "i")
    return s.lower()


EN_STOP_F = frozenset(fold(w) for w in EN_STOP)
TR_STOP_F = frozenset(fold(w) for w in TR_STOP)
NEG_EN_F = frozenset(fold(w) for w in NEG_EN)
NEG_TR_F = frozenset(fold(w) for w in NEG_TR)


def stopwords(lang: str) -> frozenset:
    return TR_STOP_F if lang == "tr" else EN_STOP_F


def tokens(text: str) -> list[str]:
    """Folded word tokens; apostrophe suffixes and English n't forms removed."""
    out = []
    for m in _WORD_RE.finditer(fold(text)):
        w = m.group()
        if w.endswith(("n't", "n’t")):
            continue
        w = w.split("'")[0].split("’")[0]
        if w:
            out.append(w)
    return out


def stem(tok: str, lang: str) -> str:
    if tok.isdigit() or len(tok) <= 3:
        return tok
    if lang == "tr":
        return tok[:5]
    t = tok
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith(("sses", "xes", "zes", "ches", "shes")):
        t = t[:-2]
    elif t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 3:
        t = t[:-1]
    if t.endswith("ing") and len(t) - 3 >= 3:
        t = t[:-3]
    elif t.endswith("ed") and len(t) - 2 >= 3:
        t = t[:-2]
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def content_tokens(text: str, lang: str) -> list[str]:
    sw = stopwords(lang)
    out = []
    for t in tokens(text):
        if t in sw or t in NEG_EN_F or t in NEG_TR_F:
            continue
        if len(t) <= 2 and not t.isdigit():
            continue
        out.append(t)
    return out


def content_stems(text: str, lang: str) -> frozenset:
    return frozenset(stem(t, lang) for t in content_tokens(text, lang))


def detect_language(text: str, default: str = "en") -> str:
    sample = text[:4000]
    toks = tokens(sample)
    if not toks:
        return default
    tr_hits = sum(t in TR_STOP_F and t not in EN_STOP_F for t in toks)
    en_hits = sum(t in EN_STOP_F and t not in TR_STOP_F for t in toks)
    tr_chars = sum(ch in _TR_CHARS for ch in sample)
    tr_score = tr_hits + 0.3 * tr_chars
    if tr_score >= 0.6 and tr_score > en_hits:
        return "tr"
    if en_hits > 0:
        return "en"
    return default


_TR_NEG_SUFFIX = re.compile(
    r"^\w{2,}(?:m[ae]d[ıiuü]\w{0,3}|m[ae]yacak\w*|m[ae]yecek\w*|m[ae]z\w{0,3}|"
    r"m[ıiuü]yor\w{0,3}|m[ae]mış\w*|m[ae]mis\w*)$")


def is_negated(text: str, lang: str) -> bool:
    low = text.lower().replace("not only", " ")
    words = re.findall(r"\w+(?:['’]\w+)*", low)
    if lang == "tr":
        for w in words:
            f = fold(w)
            if f in NEG_TR_F:
                return True
            if f in TR_NEG_EXCEPTIONS:
                continue
            if _TR_NEG_SUFFIX.match(w):
                return True
        return False
    for w in words:
        if fold(w) in NEG_EN_F or w.endswith(("n't", "n’t")):
            return True
    return False


def jaccard(a, b) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_coef(a, b) -> float:
    if min(len(a), len(b)) < 4:
        return 0.0
    return len(a & b) / min(len(a), len(b))
