"""What kind of answer does the question want?

Pr3 finding: "How tall is Mount Everest?" returned sentences that merely *mention* the
mountain ("It was named Mount Everest after ...") while the sentence holding 8,848.86 metres
was dropped, because question words such as "tall" never match "height". The profile makes
the expected answer explicit:

* kind      quantity ("how tall", "kaç", "population of") | date ("when", "hangi yıl") | open
* unit      the unit class a numeric answer should carry (len, mass, cur, pct, count, ...)
* property  stems of the asked property and its synonyms (tall = height = elevation)
* entities  the capitalised names in the question ("Mount Everest", "Norway", "Türkiye")
* years     years named in the question ("in 1856")

All of it is lexical and deterministic. No model, no hidden state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..i18n.tokenize import fold, stem, stopwords, tokens

# property groups: any word of a group stands for the whole group
_PROPS_EN = {
    "len": {"tall", "high", "height", "elevation", "altitude", "highest", "taller", "long",
            "length", "far", "distance", "wide", "width", "deep", "depth", "away"},
    "mass": {"heavy", "weight", "weigh", "weighs", "mass"},
    "count": {"many", "population", "inhabitants", "people", "residents", "populous", "number"},
    "cur": {"much", "cost", "costs", "price", "priced", "expensive", "worth", "salary"},
    "age": {"old", "age", "aged"},
    "speed": {"fast", "speed", "quick"},
    "area": {"big", "large", "area", "size", "bigger", "larger"},
}
_PROPS_TR = {  # compared on the first five letters, like the Turkish stemmer
    "len": {"yükse", "irtif", "uzunl", "mesaf", "derin", "geniş", "boyu", "metre", "kilom", "uzak"},
    "mass": {"ağırl", "kilo", "kütle"},
    "count": {"nüfus", "kişi", "insan", "sakin", "ahali"},
    "cur": {"fiyat", "ücret", "maliy", "maaş", "lira", "dolar"},
    "age": {"yaşın", "yaşı", "yaş"},
    "speed": {"hızı", "hız", "sürat"},
    "area": {"yüzöl", "alan", "büyük"},
}
_PROPS_TR = {k: {fold(w) for w in v} for k, v in _PROPS_TR.items()}   # compared on folded text
# classes whose answers carry a unit we can verify in the claim
_UNIT_CLASSES = {"len": "@len", "mass": "@mass", "cur": "@cur"}

_QTY_EN = re.compile(r"\b(?:population|how (?:tall|high|long|far|wide|deep|heavy|big|large|old|fast|many|much)|"
                     r"(?:what|which) (?:is|are|was|were) the (?:height|length|width|depth|weight|"
                     r"distance|population|area|size|speed|age|price|cost|number)|"
                     r"population of|number of)\b")
_QTY_TR = re.compile(r"\bkaç\b|\bne kadar\b|\bnüfus\w*|\bkaçtır\b")
_DATE_EN = re.compile(r"\b(?:when|what year|which year|what date|in what year)\b")
_DATE_TR = re.compile(r"\bhangi (?:yil|tarih|sene|ay)\w*|\bne zaman\b|\bkaç yilinda\b")   # folded: ı -> i
_YEAR = re.compile(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)")


@dataclass(frozen=True)
class QuestionProfile:
    kind: str = "open"                       # quantity | date | open
    unit: str | None = None                  # len | mass | cur | count | age | speed | area | None
    prop_stems: frozenset = frozenset()
    entity_stems: frozenset = frozenset()
    entities: tuple = ()
    years: tuple = ()
    function_stems: frozenset = frozenset()  # stems that only express the question form

    @property
    def unit_marker(self) -> str | None:
        return _UNIT_CLASSES.get(self.unit or "")


def question_entities(question: str, lang: str) -> tuple[str, ...]:
    """Capitalised names (adjacent words joined), the first word included unless it is a question word."""
    sw = stopwords(lang)
    out: list[list[str]] = []
    cur: list[str] = []
    for raw in re.findall(r"[\w'’-]+|[?.,;:!]", question):
        base = raw.split("'")[0].split("’")[0].strip("-")
        if base and base[0].isupper() and fold(base) not in sw and not base.isdigit() and len(base) > 1:
            cur.append(base)
        else:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return tuple(" ".join(p) for p in out)


def profile_question(question: str, lang: str) -> QuestionProfile:
    low = fold(question)
    toks = tokens(question)
    groups = _PROPS_TR if lang == "tr" else _PROPS_EN
    unit = None
    prop_words: set[str] = set()
    for name, words in groups.items():
        hit = any((t[:5] in words) if lang == "tr" else (t in words) for t in toks)
        if hit:
            prop_words |= words
            if unit is None:
                unit = name
    qty = bool(_QTY_TR.search(low)) if lang == "tr" else bool(_QTY_EN.search(low))
    date = bool(_DATE_TR.search(low)) if lang == "tr" else bool(_DATE_EN.search(low))
    kind = "quantity" if qty and not date else "date" if date else "open"
    if kind == "quantity" and unit is None:
        unit = "count" if re.search(r"how many|kaç (?:kişi|adet)|\bnumber\b", low) else None
    if kind != "quantity":
        unit = None
    ents = question_entities(question, lang)
    ent_stems = frozenset(stem(t, lang) for e in ents for t in tokens(e))
    prop_stems = frozenset(stem(w, lang) if lang != "tr" else w[:5] for w in prop_words)
    func = frozenset(stem(t, lang) for t in toks
                     if (t[:5] in prop_words if lang == "tr" else t in prop_words))
    return QuestionProfile(kind=kind, unit=unit, prop_stems=prop_stems, entity_stems=ent_stems,
                           entities=ents, years=tuple(_YEAR.findall(question)),
                           function_stems=func)


# ---------------------------------------------------------------- search helpers
def search_queries(question: str, lang: str) -> list[str]:
    """Short queries for search engines: content words and bare entity names.

    A full sentence such as "What is the population of Norway?" makes Wikipedia's search return
    "Norwegian Minnesotans"; "population Norway" and "Norway" find the right pages.
    """
    sw = stopwords(lang)
    words = [w.split("'")[0].split("’")[0] for w in re.findall(r"[\w'’-]+", question)]
    keep = [w for w in words if w and fold(w) not in sw and len(w) > 1]
    out: list[str] = []
    if keep:
        out.append(" ".join(keep))
    for e in question_entities(question, lang):
        if e not in out:
            out.append(e)
    return out or [question]


def rank_results(results: list, question: str, lang: str) -> list:
    """Order search results by how well the title matches the question's names and terms."""
    prof = profile_question(question, lang)
    ents = [fold(e) for e in prof.entities]
    q_stems = {stem(t, lang) for t in tokens(question) if t not in stopwords(lang)}
    scored = []
    for i, r in enumerate(results):
        title = fold(getattr(r, "title", "") or "")
        t_stems = {stem(t, lang) for t in tokens(title)}
        s = 0.0
        for e in ents:
            if title == e or title.startswith(e + " (") or title.startswith(e + " -"):
                s += 4.0            # the article about the named thing itself
            elif e in title:
                s += 2.0
        s += 0.5 * len(q_stems & t_stems)
        scored.append((-s, i, r))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in scored]
