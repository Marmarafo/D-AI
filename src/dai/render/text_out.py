"""Human-readable rendering of a result dict (live result or stored audit record)."""
from __future__ import annotations

STR = {
    "en": {
        "q": "Q", "none": "No supported statements found.", "dissent": "disputed by",
        "refs": "References", "balance": "evidence balance", "reliability": "source reliability",
        "strength": "evidence strength", "warnings": "Warnings",
        "sources": "sources", "stats": "Sources read: {docs}, independent: {groups}, claims: {claims}",
        "note": {"update": "time-dependent: {0} reports a different value ({1})",
                 "nuance": "{0} related claim(s) with partial overlap",
                 "approx": "values differ slightly between sources: {0}",
                 "copies": "{0} documents count as {1} independent source(s) "
                           "(same publisher or copied text)"},
        "status": {"corroborated": "corroborated", "single-source": "single source",
                   "disputed": "disputed", "mixed": "mixed evidence"},
        "disclaimer": (
            "Three separate measures: source reliability (how far a source can be trusted in general), "
            "evidence strength (how directly a quote supports the statement) and evidence balance "
            "(support versus dissent among independent sources). This is not a probability that "
            "the statement is true."),
    },
    "tr": {
        "q": "Soru", "none": "Desteklenen bir ifade bulunamadı.", "dissent": "karşı görüş",
        "refs": "Kaynaklar", "balance": "kanıt dengesi", "reliability": "kaynak güvenilirliği",
        "strength": "kanıt gücü", "warnings": "Uyarılar",
        "sources": "kaynak", "stats": "Okunan kaynak: {docs}, bağımsız: {groups}, iddia: {claims}",
        "note": {"update": "zamana bağlı: {0} farklı bir değer bildiriyor ({1})",
                 "nuance": "{0} ilgili iddia kısmen örtüşüyor",
                 "approx": "kaynaklar arasında değerler biraz farklı: {0}",
                 "copies": "{0} belge, {1} bağımsız kaynak sayılıyor "
                           "(aynı yayıncı ya da kopya metin)"},
        "status": {"corroborated": "birden fazla bağımsız kaynakla doğrulandı",
                   "single-source": "tek kaynak", "disputed": "tartışmalı",
                   "mixed": "karışık kanıt"},
        "disclaimer": (
            "Üç ayrı ölçü: kaynak güvenilirliği (kaynağa genel olarak ne kadar güvenilebilir), "
            "kanıt gücü (alıntı ifadeyi ne kadar doğrudan destekliyor) ve kanıt dengesi "
            "(bağımsız kaynaklar arasında destek ve karşı görüş dengesi). Bu, ifadenin doğru "
            "olma olasılığı değildir."),
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
        bal = s.get("evidence_balance", s.get("confidence", 0.0))     # v1 records: "confidence"
        lines.append(f"{i}. ({t['balance']} {bal * 100:.0f}%, {t['status'].get(s['status'], s['status'])}) "
                     f"{s['statement']} {marks}")
        strengths = [e for e in s["supporting"] if e.get("evidence_strength") is not None]
        if strengths:
            lines.append(f"   {t['strength']}: " + ", ".join(
                f"[{e['ref']}] {e['evidence_strength'] * 100:.0f}" for e in strengths))
        for e in s["dissent"][:3]:
            q = e["quote"]
            q = q if len(q) <= 140 else q[:137].rstrip() + "..."
            lines.append(f"   {t['dissent']}: \"{q}\" [{e['ref']}]")
        for n in s["notes"]:
            lines.append(f"   - {_fmt_note(t, n)}")
    lines += ["", f"{t['refs']}:"]
    for r in d["references"]:
        rel = r.get("source_reliability", r.get("trust"))             # v1 records: "trust"
        trust = f" ({t['reliability']} {rel * 100:.0f})" if rel is not None else ""
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
