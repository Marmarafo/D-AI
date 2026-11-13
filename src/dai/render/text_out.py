"""Human-readable rendering of a result dict (live result or stored audit record)."""
from __future__ import annotations

STR = {
    "en": {
        "q": "Q", "none": "No supported statements found.", "dissent": "disputed by",
        "refs": "References", "trust": "trust", "warnings": "Warnings",
        "sources": "sources", "stats": "Sources read: {docs}, independent: {groups}, claims: {claims}",
        "note": {"update": "time-dependent: {0} reports a different value ({1})",
                 "nuance": "{0} related claim(s) with partial overlap"},
        "status": {"corroborated": "corroborated", "single-source": "single source",
                   "disputed": "disputed", "mixed": "mixed evidence"},
        "disclaimer": "Confidence is an evidence-balance indicator, not a probability of truth.",
    },
    "tr": {
        "q": "Soru", "none": "Desteklenen bir ifade bulunamadı.", "dissent": "karşı görüş",
        "refs": "Kaynaklar", "trust": "güven", "warnings": "Uyarılar",
        "sources": "kaynak", "stats": "Okunan kaynak: {docs}, bağımsız: {groups}, iddia: {claims}",
        "note": {"update": "zamana bağlı: {0} farklı bir değer bildiriyor ({1})",
                 "nuance": "{0} ilgili iddia kısmen örtüşüyor"},
        "status": {"corroborated": "birden fazla bağımsız kaynakla doğrulandı",
                   "single-source": "tek kaynak", "disputed": "tartışmalı",
                   "mixed": "karışık kanıt"},
        "disclaimer": "Güven değeri bir kanıt dengesi göstergesidir, doğruluk olasılığı değildir.",
    },
}


def _fmt_note(t: dict, n: dict) -> str:
    tpl = t["note"].get(n["code"])
    return tpl.format(*n["args"]) if tpl else f"{n['code']}: {n['args']}"


def render_text(d: dict, lang: str | None = None) -> str:
    lang = lang or d.get("output_language", "en")
    t = STR.get(lang, STR["en"])
    lines = [f"{t['q']}: {d['query']}", ""]
    if not d["statements"]:
        lines.append(t["none"])
    for i, s in enumerate(d["statements"], 1):
        marks = ",".join(f"[{e['ref']}]" for e in s["supporting"])
        lines.append(f"{i}. ({s['confidence'] * 100:.0f}%, {t['status'].get(s['status'], s['status'])}) "
                     f"{s['statement']} {marks}")
        for e in s["dissent"][:3]:
            q = e["quote"]
            q = q if len(q) <= 140 else q[:137].rstrip() + "..."
            lines.append(f"   {t['dissent']}: \"{q}\" [{e['ref']}]")
        for n in s["notes"]:
            lines.append(f"   - {_fmt_note(t, n)}")
    lines += ["", f"{t['refs']}:"]
    for r in d["references"]:
        trust = f" ({t['trust']} {r['trust'] * 100:.0f})" if r.get("trust") is not None else ""
        lines.append(f"[{r['ref']}] {r['title'] or r['url']} — {r['url']}{trust}")
    st = d.get("stats", {})
    if st:
        lines += ["", t["stats"].format(docs=st.get("documents", 0),
                                        groups=st.get("independent_groups", 0),
                                        claims=st.get("claims_relevant", 0))]
    if d.get("errors"):
        lines += ["", f"{t['warnings']}:"] + [f"  - {e}" for e in d["errors"]]
    lines += ["", t["disclaimer"]]
    return "\n".join(lines)
