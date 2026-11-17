"""Numbers, units and dates: extraction and normalisation (English + Turkish).

All functions operate on *folded* text (see i18n.tokenize.fold).
"""
from __future__ import annotations

import re

from ..i18n.tokenize import fold, stem, stopwords

_MONTH_NAMES = [
    ["january", "jan", "ocak"], ["february", "feb", "şubat", "subat"], ["march", "mar", "mart"],
    ["april", "apr", "nisan"], ["may", "mayis"], ["june", "jun", "haziran"],
    ["july", "jul", "temmuz"], ["august", "aug", "ağustos", "agustos"],
    ["september", "sep", "sept", "eylül", "eylul"], ["october", "oct", "ekim"],
    ["november", "nov", "kasim"], ["december", "dec", "aralik"],
]
MONTHS = {fold(n): i for i, names in enumerate(_MONTH_NAMES, 1) for n in names}

MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
        "bin": 1e3, "milyon": 1e6, "milyar": 1e9, "trilyon": 1e12}
UNITS = {  # word -> (class, factor to base)
    "mm": ("len", 0.001), "cm": ("len", 0.01), "m": ("len", 1.0), "km": ("len", 1000.0),
    "metre": ("len", 1.0), "metres": ("len", 1.0), "meter": ("len", 1.0), "meters": ("len", 1.0),
    "kilometre": ("len", 1000.0), "kilometres": ("len", 1000.0), "kilometer": ("len", 1000.0),
    "kilometers": ("len", 1000.0), "mile": ("len", 1609.344), "miles": ("len", 1609.344),
    "ft": ("len", 0.3048), "feet": ("len", 0.3048), "foot": ("len", 0.3048),
    "inch": ("len", 0.0254), "inches": ("len", 0.0254), "yard": ("len", 0.9144),
    "yards": ("len", 0.9144), "yd": ("len", 0.9144),
    "mg": ("mass", 0.001), "g": ("mass", 1.0), "gram": ("mass", 1.0), "kg": ("mass", 1000.0),
    "kilogram": ("mass", 1000.0), "kilograms": ("mass", 1000.0), "kilo": ("mass", 1000.0),
    "ton": ("mass", 1e6), "tons": ("mass", 1e6), "tonne": ("mass", 1e6), "tonnes": ("mass", 1e6),
    "lb": ("mass", 453.592), "lbs": ("mass", 453.592),
}
PCT_WORDS = {"percent", "yuzde", "yüzde", "pct"}
CUR_WORDS = {"dollar", "dollars", "usd", "euro", "euros", "eur", "tl", "lira", "pound", "pounds",
             "gbp", "dolar", "avro", "sterlin"}
_NONQTY = set(MULT) | set(UNITS) | PCT_WORDS | CUR_WORDS

_P_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_P_DMY = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+([^\W\d_]{3,9})\.?,?\s+(\d{4})(?!\d)")
_P_MDY = re.compile(r"(?<!\w)([^\W\d_]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
_P_NUMDATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_P_MY = re.compile(r"(?<!\w)([^\W\d_]{3,9})\.?,?\s+(\d{4})(?!\d)")
_P_DM = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+([^\W\d_]{3,9})(?!\w)")
_P_YEAR = re.compile(r"(?<![\d.,\-/$€£₺])((?:19|20)\d{2})(?!\d|[.,]\d)")
# years before 1900 are ambiguous with plain numbers ("1500 people"): accept them only with a
# year cue before ("in 1453", "since 1856", "around 1856") or after ("1453 yılında", "1066 AD")
_P_OLD_YEAR = re.compile(r"(?<![\d.,\-/$€£₺])(1[0-8]\d{2})(?!\d|[.,]\d)")
# (text is folded before it gets here: Turkish dotless ı is already i)
_YEAR_BEFORE = re.compile(r"(?:\b(?:in|since|by|until|till|from|around|circa|ca|c|before|after|during|"
                          r"between|year|yil|yili|tarihinde)\.?\s+)$")
_YEAR_AFTER = re.compile(r"\s*(?:yilinda|yili|yilina|yilindan|senesinde|ad\b|a\.d|bc\b|b\.c|ce\b|bce\b|"
                         r"m\.o|m\.s)")
_NUM = re.compile(r"\d[\d.,]*\d|\d")


def _iso(y, m=None, d=None) -> str | None:
    if m is not None and not 1 <= m <= 12:
        return None
    if d is not None and not 1 <= d <= 31:
        return None
    s = f"{y:04d}"
    if m is not None:
        s += f"-{m:02d}"
        if d is not None:
            s += f"-{d:02d}"
    return s


def _mask(t: str, m: re.Match) -> str:
    return t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]


def extract_dates(t: str, lang: str = "en") -> tuple[tuple, str]:
    """Return (sorted ISO-partial dates, text with date spans blanked out)."""
    found: set[str] = set()

    def run(pat, build):
        nonlocal t
        for m in list(pat.finditer(t)):
            res = build(m)
            if res is None:
                continue
            if res:
                found.add(res)
            t = _mask(t, m)

    run(_P_ISO, lambda m: _iso(int(m[1]), int(m[2]), int(m[3])))
    run(_P_DMY, lambda m: (_iso(int(m[3]), MONTHS[m[2]], int(m[1])) if m[2] in MONTHS else None))
    run(_P_MDY, lambda m: (_iso(int(m[3]), MONTHS[m[1]], int(m[2])) if m[1] in MONTHS else None))

    def numdate(m):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            day, mon = a, b
        elif b > 12:
            day, mon = b, a
        else:
            day, mon = (a, b) if lang == "tr" else (b, a)
        return _iso(y, mon, day)

    run(_P_NUMDATE, numdate)
    run(_P_MY, lambda m: (_iso(int(m[2]), MONTHS[m[1]]) if m[1] in MONTHS else None))
    run(_P_DM, lambda m: ("" if m[2] in MONTHS else None))  # day+month, no year: mask only

    for m in list(_P_YEAR.finditer(t)):
        rest = t[m.end():m.end() + 24]
        nxt = re.match(r"\s*(%|[^\W\d_]+)", rest)
        if nxt and (nxt[1] == "%" or nxt[1] in _NONQTY):
            continue
        found.add(m[1])
        t = _mask(t, m)
    for m in list(_P_OLD_YEAR.finditer(t)):
        before = t[max(0, m.start() - 14):m.start()]
        rest = t[m.end():m.end() + 24]
        if _YEAR_BEFORE.search(before) or _YEAR_AFTER.match(rest):
            if not re.match(r"\s*(%|[^\W\d_]+)", rest) or \
                    re.match(r"\s*([^\W\d_]+)", rest)[1] not in _NONQTY:
                found.add(m[1])
                t = _mask(t, m)
    return tuple(sorted(found)), t


def dates_incompatible(a: tuple, b: tuple) -> bool:
    """True when both sides carry dates and no pair is compatible (prefix-wise)."""
    if not a or not b:
        return False
    return not any(x.startswith(y) or y.startswith(x) for x in a for y in b)


def _parse_number(raw: str) -> float | None:
    s = raw
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2:
            if all(len(p) == 3 for p in parts[1:]):
                s = "".join(parts)
            else:
                return None
        else:
            a, b = parts
            if len(b) == 3 and 1 <= len(a) <= 3 and a != "0":
                s = a + b
            else:
                s = a + "." + b
    try:
        return float(s)
    except ValueError:
        return None


def _words(s: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", s)


def extract_quantities(t: str, lang: str = "en") -> list[tuple[float, frozenset]]:
    """Numbers with context markers (unit class, neighbouring content stems)."""
    sw = stopwords(lang)
    out: list[tuple[float, frozenset]] = []
    for m in _NUM.finditer(t):
        s, e = m.span()
        prev = t[s - 1] if s > 0 else " "
        if prev.isalpha() or (prev in "-_/" and s > 1 and t[s - 2].isalpha()):
            continue
        rest = t[e:e + 40]
        if re.match(r"(?:st|nd|rd|th)\b", rest):
            continue
        lead = re.match(r"[^\W\d_]+", rest)
        if lead and lead.group() not in _NONQTY:
            continue  # letters glued to the number that are not a unit (5x, 12ab)
        val = _parse_number(m.group())
        if val is None:
            continue
        markers: set[str] = set()
        before = t[max(0, s - 40):s]
        prev_words = _words(before)
        next_words = _words(rest if not rest.startswith("%") else rest[1:])
        if prev and prev in "$€£₺" or (before.rstrip()[-1:] in "$€£₺" if before.strip() else False):
            markers.add("@cur")
        if rest.startswith("%") or rest.lstrip().startswith("%"):
            markers.add("@pct")
        if prev_words and prev_words[-1] in PCT_WORDS:
            markers.add("@pct")
        # unit words must follow the number directly ("5.91 billion km"); a second quantity after
        # punctuation ("... km; 3.67 billion mi") must not be consumed by this one
        adjacent: list[str] = []
        pos = 1 if rest.startswith("%") else 0
        while True:
            mm = re.match(r"[ \t]*([^\W\d_]+)", rest[pos:])
            if not mm or mm.group(1) not in _NONQTY:
                break
            adjacent.append(mm.group(1))
            pos += mm.end()
        consumed = 0
        while consumed < len(adjacent):
            w = adjacent[consumed]
            if w in MULT:
                val *= MULT[w]
            elif w in UNITS:
                cls, fac = UNITS[w]
                val *= fac
                markers.add("@" + cls)
            elif w in PCT_WORDS:
                markers.add("@pct")
            elif w in CUR_WORDS:
                markers.add("@cur")
            consumed += 1
        ctx_prev = [w for w in prev_words if w not in sw and w not in _NONQTY and len(w) > 2]
        ctx_next = [w for w in next_words[consumed:] if w not in sw and len(w) > 2]
        if ctx_prev:
            markers.add(stem(ctx_prev[-1], lang))
        if ctx_next:
            markers.add(stem(ctx_next[0], lang))
        out.append((val, frozenset(markers)))
    return out


def extract_features(text: str, lang: str):
    """(numbers, num_ctx, dates) for a sentence."""
    t = fold(text)
    dates, masked = extract_dates(t, lang)
    q = extract_quantities(masked, lang)
    seen = []
    nums, ctxs = [], []
    for v, c in q:
        key = round(v, 6)
        if key in seen:
            continue
        seen.append(key)
        nums.append(v)
        ctxs.append(c)
    return tuple(nums), tuple(ctxs), dates
