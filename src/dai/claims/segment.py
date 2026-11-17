"""Sentence segmentation and claim construction."""
from __future__ import annotations

import re
from dataclasses import replace

from ..core.models import Claim
from ..i18n.stopwords import ABBR
from ..i18n.tokenize import (content_stems, content_tokens, detect_language, fold,
                             is_negated, stem, stopwords, tokens)
from .normalize import MONTHS, extract_features

# footnote / editorial markers: [25], [h], [citation needed], [25]: 136 ...
_CITE = re.compile(r"\[(?:\d{1,3}|[a-z]|[ivx]{1,4}|citation needed|clarification needed|"
                   r"when\?|who\?|note \d+|nb \d+|dubious[^\]]{0,20}|better source needed)\]"
                   r"(?:\s*:\s*\d+(?:[–-]\d+)?)?", re.I)
# hatnotes, captions, navigation and housekeeping lines that are not statements about the world
_NOT_CLAIM = re.compile(
    r"(?i)^(?:from wikipedia\b|this article is about\b|for other uses\b|for the \w+[^.]{0,40}, see\b|"
    r"for \w+(?: \w+){0,4}, see\b|see also\b|further information\b|main articles?\b|"
    r"\W*redirects? here\b|\W*\u2191|this section (?:needs|is)\b|please help\b|"
    r"the reason given is\b|file\s*[-–:]|\(?ap photo|photo by\b|image:|"
    r"bu madde\b.{0,60}\bhakkında|ana madde\b|ayrıca bakınız|ayrıca bkz|"
    r"bu maddede\b.{0,160}\b(?:bulunur|yer alır|ele alınır))"
    r"|\bfile photo\b|\u00b7|\bredirects? here\b|^\W*\u2191")
_END = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+|$)")
_BOILER = re.compile(
    r"(?i)(?:\b(?:cookies?|çerez\w*|all rights reserved|tüm hakları saklıdır|subscribe|newsletter|"
    r"sign up|log ?in|follow us|share this|advertisement|reklam|abone ol|privacy policy|"
    r"gizlilik politikası|terms of (?:use|service)|read more|devamını oku|click here|"
    r"yorum yap|related articles?|ilgili haberler|photo:|fotoğraf:|getty images)\b|©)")

EN_VERBS = set("""is are was were be been being am has have had will would can could may might do does did
said says say reported announced rose rise rises fell fall falls increased increase increases
decreased decrease decreases reached reaches grew grow grows dropped drop drops declined
declines approved approves signed signs launched launches released releases won wins lost
loses died dies killed kills found finds showed shows estimated estimates totaled totals
stands stand stood remains remained became becomes caused causes confirmed confirms denied
denies expects expected plans planned began begins started starts ended ends opened opens
closed closes ordered orders voted votes passed passes measures measured contains contained
includes included costs cost covers covered employs employed houses housed seats seated
weighs weighed""".split())
_IRREG = {"is": "be", "are": "be", "was": "be", "were": "be", "been": "be", "being": "be",
          "am": "be", "has": "have", "have": "have", "had": "have", "rose": "rise",
          "rises": "rise", "fell": "fall", "falls": "fall", "grew": "grow", "grows": "grow",
          "won": "win", "wins": "win", "lost": "lose", "loses": "lose", "said": "say",
          "says": "say", "stood": "stand", "stands": "stand", "began": "begin",
          "became": "become", "found": "find", "finds": "find", "died": "die", "dies": "die"}

_OPINION = re.compile(
    r"(?i)\b(i think|i believe|in my opinion|arguably|should|best|worst|greatest|amazing|terrible|"
    r"beautiful|unfortunately|obviously|i feel|we believe|probably|perhaps|bence|bana göre|"
    r"bize göre|en iyi|en kötü|olmalı\w*|harika|korkunç|maalesef|açıkça|muhtemelen)\b")
_FORECAST = re.compile(
    r"(?i)\b(will|is expected to|are expected to|is projected|are projected|forecast\w*|"
    r"predicted|is set to|plans? to|expected to|bekleniyor|öngörülüyor|tahmin ediliyor|"
    r"planlanıyor)\b")
_TR_FUTURE_END = re.compile(r"(?i)(acak|ecek|acaktır|ecektir)$")
_QUOTE = re.compile(r"[\"“«]([^\"“”«»]{20,})[\"”»]")


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    pos = 0
    for para in re.split(r"\n\s*\n", text):
        pstart = text.find(para, pos)
        if pstart < 0:
            pstart = pos
        pos = pstart + len(para)
        start = 0
        for m in _END.finditer(para):
            punct = m.group(1)
            after = para[m.end():m.end() + 1]
            if m.group(2) != "" and after:
                if punct.startswith(".") and not any(c in punct for c in "!?…"):
                    word = para[start:m.start()].split()[-1:] or [""]
                    w = word[0]
                    wl = fold(w).rstrip(".").strip("\"'“‘(")
                    if wl in {fold(a) for a in ABBR}:
                        continue
                    if len(w) == 1 and w.isalpha() and w.isupper():
                        continue
                    if re.fullmatch(r"(?:\w\.)+\w", w):
                        continue
                if after.islower():
                    continue
            end = m.end(1)
            s = para[start:end].strip()
            if s:
                out.append((s, pstart + start, pstart + end))
            start = m.end()
        tail = para[start:].strip()
        if tail:
            out.append((tail, pstart + start, pstart + len(para)))
    return out


def _entities(text: str, lang: str) -> frozenset:
    sw = stopwords(lang)
    words = re.findall(r"[\w'’-]+", text)
    ents = set()
    for i, w in enumerate(words):
        base = w.split("'")[0].split("’")[0].strip("-")
        if len(base) < 2 or base.isdigit():
            continue
        f = fold(base)
        if f in sw or f in MONTHS:
            continue
        cap = base[0].isupper()
        nxt_cap = i + 1 < len(words) and words[i + 1][:1].isupper()
        if (cap and (i > 0 or nxt_cap)) or (base.isupper() and len(base) > 1):
            ents.add(f)
    return frozenset(ents)


def _norm_verb(w: str) -> str:
    if w in _IRREG:
        return _IRREG[w]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2].rstrip("e") if not w.endswith("eed") else w[:-2]
    return stem(w, "en")


def _subject_predicate(text: str, lang: str) -> tuple[str, str, str]:
    words = tokens(text)
    sw = stopwords(lang)
    if len(words) < 2:
        return "", "", ""
    if lang == "tr":
        pred = words[-1][:4]
        subj = [t for t in words[:-1] if t not in sw and not t.isdigit()][:3]
        value = " ".join(t for t in words[:-1] if t not in subj)
        return " ".join(subj), pred, value
    idx = None
    for i, w in enumerate(words):
        if i >= 1 and (w in EN_VERBS or (w.endswith("ed") and len(w) > 4)):
            idx = i
            break
    if idx is None:
        subj = [t for t in words if t not in sw][:3]
        return " ".join(subj), "", " ".join(words[len(subj):])
    subj = [t for t in words[:idx] if t not in sw][:5]
    value = [t for t in words[idx + 1:] if t not in sw]
    return " ".join(subj), _norm_verb(words[idx]), " ".join(value)


def classify_type(text: str, lang: str, numbers: tuple) -> str:
    m = _QUOTE.search(text)
    if m and len(m.group(1).split()) >= 5:
        return "quote"
    if _OPINION.search(text):
        return "opinion"
    last = (re.findall(r"\w+", text) or [""])[-1]
    if _FORECAST.search(text) or (lang == "tr" and _TR_FUTURE_END.search(last)):
        return "forecast"
    if numbers:
        return "statistic"
    return "fact"


def make_claim(text: str, lang: str, doc_url: str = "", start: int = 0, end: int = 0) -> Claim:
    norm = " ".join(fold(text).split())
    numbers, ctx, dates = extract_features(text, lang)
    subj, pred, val = _subject_predicate(text, lang)
    return Claim(
        text=text, normalized=norm, lang=lang,
        claim_type=classify_type(text, lang, numbers),
        subject=subj, predicate=pred, value=val,
        numbers=numbers, num_ctx=ctx, dates=dates,
        negated=is_negated(text, lang),
        entities=_entities(text, lang), stems=content_stems(text, lang),
        doc_url=doc_url, start=start, end=end)


def clean_sentence(s: str) -> str:
    s = _CITE.sub("", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return " ".join(s.split())


def _acceptable(s: str) -> bool:
    if len(s) < 30 or len(s) > 450 or s.endswith("?") or s.endswith(":"):
        return False
    if _NOT_CLAIM.search(s):
        return False
    if len(s.split()) < 5:
        return False
    if _BOILER.search(s):
        return False
    letters = sum(c.isalpha() for c in s)
    if letters / len(s) < 0.6:
        return False
    if s.isupper():
        return False
    return True


def extract_claims(text: str, doc_url: str = "", lang: str | None = None,
                   max_claims: int = 80, keep=None) -> list[Claim]:
    """keep(sentence) -> bool is an optional cheap pre-filter run before the full claim is built."""
    lang = lang or detect_language(text)
    seen: set[str] = set()
    out: list[Claim] = []
    for s, a, b in split_sentences(text):
        s = clean_sentence(s)
        if not _acceptable(s):
            continue
        if keep is not None and not keep(s):
            continue
        c = make_claim(s, lang, doc_url, a, b)
        if c.normalized in seen or len(c.stems) < 2:
            continue
        seen.add(c.normalized)
        out.append(c)
        if len(out) >= max_claims:
            break
    return out


def with_relevance(c: Claim, rel: float) -> Claim:
    return replace(c, relevance=rel)
