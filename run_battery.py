"""D-AI live test battery (needs internet).

    python run_battery.py            # all 10 cases + extra command checks
    python run_battery.py --only 3 4 # selected cases (case 9 needs case 3)
    python run_battery.py --list     # show the cases and exit

Everything runs in an isolated data directory (battery_out/home), so your normal D-AI database,
cache and source tiers are not touched. Output: battery_out/battery_report.md (summary + details)
and battery_out.zip (the whole folder, easy to share).

Check statuses
  PASS   behaves as intended
  FAIL   should work today but does not (a regression or a new bug)
  KNOWN  fails today and is already on the roadmap (the Pr3 baseline)
  WARN   environment or network problem (page unreachable, ...): not a D-AI verdict
  INFO   an observation to read by eye, no verdict
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "battery_out"
HOME = OUT / "home"
sys.path.insert(0, str(ROOT / "src"))

# Real pages found for this battery. AP_* are the same Associated Press story on different
# local-TV sites (a syndication test); the others are independent publishers.
BRIT = "https://www.britannica.com/place/Mount-Everest/The-height-of-Everest"
DAWN = "https://www.dawn.com/news/1594790"
GUIN = "https://guinnessworldrecords.com.br/world-records/highest-mountain"
AP_1 = "https://weartv.com/news/nation-world/height-of-mt-everest-taller-than-earlier-reported-1"
AP_2 = "https://newschannel9.com/news/nation-world/height-of-mt-everest-taller-than-earlier-reported-1"
AP_3 = "https://kutv.com/news/nation-world/height-of-mt-everest-taller-than-earlier-reported-1"
EVEREST_URLS = [BRIT, DAWN, GUIN, AP_1, AP_2, AP_3]
AP_URLS = [AP_1, AP_2, AP_3]
PLUTO = "https://en.wikipedia.org/wiki/Pluto"

CASES = {
    1: "TR nüfus sorusu (Wikipedia): soruya cevap veren cümleler mi geliyor?",
    2: "TR soru + İngilizce kaynaklar: diller arası eşleşme sınırı",
    3: "Everest: AP haberinin 3 kopyası tek bağımsız kaynak sayılıyor mu? (madde 02)",
    4: "Everest 1856: kaynaklar arası sayı/tarih uyuşmazlığı (madde 03)",
    5: "Plüton: olumsuzluk (negation) ve `claims` komutu",
    6: "Dünya nüfusu: zamana bağlı değerler (update ilişkisi)",
    7: "Yapay zekâ: görüş/tahmin cümleleri filtreleniyor mu?",
    8: "Eyfel: --agent modu, bütçe ve durma nedeni",
    9: "Tekrarlanabilirlik: aynı koşu --offline + audit ile aynı sonucu veriyor mu?",
    10: "Dayanıklılık: bozuk/yasak/olmayan URL, anlamsız soru, boş soru",
}


class Case:
    def __init__(self, n: int):
        self.n, self.title = n, CASES[n]
        self.checks: list[tuple[str, str, str]] = []
        self.commands: list[str] = []
        self.notes: list[str] = []
        self.seconds = 0.0

    def check(self, ok: bool, name: str, detail: str = "", known: str | None = None):
        status = "PASS" if ok else ("KNOWN" if known else "FAIL")
        if not ok and known:
            detail = f"{detail} [yol haritası: {known}]".strip()
        self.checks.append((status, name, detail))

    def warn(self, name: str, detail: str = ""):
        self.checks.append(("WARN", name, detail))

    def info(self, name: str, detail: str = ""):
        self.checks.append(("INFO", name, detail))

    def counts(self) -> dict:
        c: dict = {}
        for s, _, _ in self.checks:
            c[s] = c.get(s, 0) + 1
        return c


class Proc:
    def __init__(self, rc, out, err, secs, cmd):
        self.rc, self.out, self.err, self.secs, self.cmd = rc, out, err, secs, cmd

    @property
    def run_id(self):
        m = re.search(r"run id: (\d+)", self.err)
        return int(m.group(1)) if m else None

    def json(self):
        try:
            return json.loads(self.out)
        except ValueError:
            return None


def run_dai(args: list[str], case: Case | None = None, timeout: int = 300) -> Proc:
    env = dict(os.environ, DAI_HOME=str(HOME), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(ROOT / "run_dai.py"), *args]
    shown = "python run_dai.py " + " ".join(f'"{a}"' if " " in a or "'" in a else a for a in args)
    if case is not None:
        case.commands.append(shown)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, env=env, timeout=timeout)
        rc, out, err = p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"TIMEOUT after {timeout}s"
    secs = time.perf_counter() - t0
    if case is not None:
        case.seconds += secs
    return Proc(rc, out, err, secs, shown)


def research(question, urls=(), extra=(), case=None, json_out=True) -> Proc:
    a = ["research", question]
    for u in urls:
        a += ["--url", u]
    a += list(extra)
    if json_out:
        a.append("--json")
    return run_dai(a, case)


def no_traceback(*texts) -> bool:
    return not any("Traceback (most recent call last)" in (t or "") for t in texts)


def statements(d) -> list:
    return (d or {}).get("statements", [])


def all_evidence(d) -> list:
    return [e for s in statements(d) for e in s.get("supporting", []) + s.get("dissent", [])]


def big_numbers(text: str) -> list[int]:
    vals = []
    for m in re.finditer(r"\d{1,3}(?:[.,]\d{3})+|\d{7,}", text):
        vals.append(int(re.sub(r"\D", "", m.group(0))))
    return [v for v in vals if v >= 1_000_000]


def short(t: str, n: int = 150) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[: n - 3] + "..."


def top_lines(d, k=5) -> str:
    lines = []
    for s in statements(d)[:k]:
        lines.append(f"{s['status']:13s} denge={s['evidence_balance']:.2f} "
                     f"bağımsız={s['independent_sources']}  {short(s['statement'])}")
    return "\n".join(lines) or "(ifade yok)"


def get_trace(run_id, case):
    if run_id is None:
        return None
    p = run_dai(["audit", str(run_id), "--format", "trace"], case)
    try:
        return json.loads(p.out)
    except ValueError:
        return None


def three_measures_ok(d) -> tuple[bool, str]:
    ev = all_evidence(d)
    if not ev:
        return True, "kanıt yok"
    bad = [e for e in ev if "source_reliability" not in e or "evidence_strength" not in e or "trust" in e]
    st_bad = [s for s in statements(d) if "evidence_balance" not in s or "confidence" in s]
    return (not bad and not st_bad), f"{len(bad)} kanıt, {len(st_bad)} ifade şemaya uymuyor"


def no_data(c: Case, d) -> bool:
    """True (and a WARN) when no page could be read: a network problem, not a D-AI verdict."""
    if d is not None and d.get("stats", {}).get("documents", 0) == 0:
        c.warn("hiç sayfa okunamadı; vaka değerlendirilmedi (ağ/kaynak sorunu)",
               short(" | ".join(d.get("errors", [])), 250))
        return True
    return False


def base_checks(c: Case, p: Proc, d, allow_rc=(0, 3)):
    c.check(p.rc in allow_rc, "program çökmeden bitti", f"çıkış kodu {p.rc}")
    c.check(no_traceback(p.out, p.err), "Traceback yok")
    c.check(d is not None, "çıktı geçerli JSON")
    if d is not None:
        ok, det = three_measures_ok(d)
        c.check(ok, "üç ölçü ayrı alanlarda (güvenilirlik/kanıt gücü/denge)", det)
        c.check(d.get("schema") == "dai.result/2", "şema dai.result/2", str(d.get("schema")))
        if d.get("errors"):
            c.info("uyarılar", " | ".join(short(e, 120) for e in d["errors"][:6]))


# ------------------------------------------------------------------ cases
def case1(ctx):
    c = Case(1)
    p = research("Türkiye'nin nüfusu kaç?", case=c)
    d = p.json()
    base_checks(c, p, d)
    sts = statements(d)
    if no_data(c, d):
        return c, p
    top3 = sts[:3]
    c.check(any(big_numbers(s["statement"]) for s in top3),
            "ilk 3 ifadeden biri nüfus rakamı içeriyor (>= 1 milyon)",
            "soruya cevap veren cümle üst sıralarda değil")
    c.check(not any(re.search(r"\[\d+\]", s["statement"]) for s in sts),
            "ifadelerde dipnot işareti [25] kalmamış", "dipnot metne sızıyor")
    c.check(not any(s["statement"].rstrip().endswith(":") for s in sts),
            "yarım biten (':' ile biten) ifade yok", "")
    off = [s for s in sts if not re.search(r"\d", s["statement"])]
    c.info("rakamsız (muhtemelen konu dışı) ifade sayısı", f"{len(off)} / {len(sts)}")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case2(ctx):
    c = Case(2)
    p = research("Everest'in yüksekliği kaç metre?", urls=[BRIT, DAWN], extra=["--lang", "tr"], case=c)
    d = p.json()
    base_checks(c, p, d)
    if no_data(c, d):
        return c, p
    n = len(statements(d))
    c.info("TR soru, EN kaynak: bulunan ifade sayısı", f"{n} (README: diller arası eşleşme desteklenmiyor)")
    c.info("ilk ifadeler", "\n" + top_lines(d))
    return c, p


def case3(ctx):
    c = Case(3)
    p = research("How tall is Mount Everest?", urls=EVEREST_URLS, extra=["--trace"], case=c)
    d = p.json()
    ctx["case3_proc"], ctx["case3_json"] = p, d
    base_checks(c, p, d)
    if d is None:
        return c, p
    docs = d["stats"].get("documents", 0)
    ctx["case3_run_id"] = p.run_id
    if docs < 4:
        c.warn(f"yalnızca {docs}/{len(EVEREST_URLS)} sayfa okunabildi; bağımsızlık vakası değerlendirilmedi",
               short(" | ".join(d.get("errors", [])), 250))
        ctx["case3_json"] = None
        return c, p
    tr = get_trace(p.run_id, c)
    if tr:
        grp = {x["url"]: x["group"] for x in tr["documents"]}
        ap = [grp[u] for u in AP_URLS if u in grp]
        if len(ap) >= 2:
            c.check(len(set(ap)) == 1, f"{len(ap)} AP kopyası tek bağımsız grupta", f"gruplar: {sorted(set(ap))}",
                    known="02 bağımsız kaynak gruplama")
        else:
            c.warn("AP kopyalarından <2 tanesi okunabildi", f"okunan: {len(ap)}")
        others = [grp[u] for u in (BRIT, DAWN, GUIN) if u in grp]
        c.check(len(set(others)) == len(others), "Britannica/Dawn/Guinness birbirinden bağımsız",
                f"gruplar: {others}")
        if ap and others:
            c.check(not (set(ap) & set(others)), "AP grubu bağımsız yayıncılarla birleşmemiş (aşırı birleştirme yok)")
        c.info("belge -> grup", "\n" + "\n".join(f"{x['group']}  {x['domain']}" for x in tr["documents"]))
    sts = statements(d)
    c.check(any(s["independent_sources"] >= 2 for s in sts), "en az bir ifade >= 2 bağımsız kaynakla destekleniyor")
    c.check(any(n["code"] == "copies" for s in sts for n in s.get("notes", [])),
            "kopya belgeler 'N belge, M bağımsız kaynak sayılıyor' notuyla belirtildi")
    c.check(any(re.search(r"8,?848", s["statement"]) for s in sts[:3]),
            "ilk 3 ifadeden biri Everest'in yükseklik rakamını (8,848...) veriyor")
    disp = [s for s in sts if s["status"] in ("disputed", "mixed")]
    c.info("tartışmalı/karışık ifadeler (feet/metre yüzünden mi diye gözle bak)",
           "\n".join(f"{s['status']}: {short(s['statement'], 110)}  <-> "
                     f"{short(s['dissent'][0]['quote'], 90) if s['dissent'] else ''}" for s in disp[:5]) or "yok")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case4(ctx):
    c = Case(4)
    p = research("How tall was Mount Everest in 1856?", urls=EVEREST_URLS, case=c)
    d = p.json()
    ctx["case4_run_id"] = p.run_id
    base_checks(c, p, d)
    if d is None or no_data(c, d):
        return c, p
    mention = [s for s in statements(d) if "1856" in s["statement"]]
    c.check(bool(mention), "1856'yı anan en az bir ifade bulundu")
    rel = {}
    tr = get_trace(p.run_id, c)
    if tr:
        for cl in tr["clusters"]:
            for r in cl["relations"]:
                rel[r["kind"]] = rel.get(r["kind"], 0) + 1
        c.info("ilişki türleri", json.dumps(rel, ensure_ascii=False))
        contr = [r for cl in tr["clusters"] for r in cl["relations"] if r["kind"] == "contradiction"]
        c.info("çelişki sinyalleri", "\n".join(short("; ".join(r["signals"]), 160) for r in contr[:6]) or "yok")
    c.info("beklenen: Dawn 8,840 m vs AP 8,842 m", "bu fark çelişki/nüans olarak görünmeli; elle bak")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case5(ctx):
    c = Case(5)
    p = research("Is Pluto a planet?", urls=[PLUTO], extra=["--lang", "en"], case=c)
    d = p.json()
    base_checks(c, p, d)
    if no_data(c, d):
        return c, p
    q = run_dai(["claims", PLUTO, "--limit", "400"], c)
    c.check(no_traceback(q.out, q.err), "`claims` komutu çökmedi")
    if q.rc != 0:
        c.warn("`claims`: sayfa alınamadı", short(q.out + q.err, 200))
    else:
        neg = [ln for ln in q.out.splitlines() if "negated=True" in ln]
        c.check(len(neg) >= 1, "en az bir olumsuz (negated) iddia çıkarıldı", f"{len(neg)} adet")
    c.info("'not'/'dwarf' içeren ifadeler",
           "\n".join(short(s["statement"], 140) for s in statements(d)
                     if re.search(r"\bnot\b|no longer|dwarf", s["statement"], re.I))[:900] or "yok")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case6(ctx):
    c = Case(6)
    p = research("What is the world population?", extra=["--lang", "en"], case=c)
    d = p.json()
    base_checks(c, p, d)
    if no_data(c, d):
        return c, p
    notes = [n for s in statements(d) for n in s.get("notes", [])]
    c.info("not türleri", json.dumps({k: sum(1 for n in notes if n["code"] == k) for k in {n["code"] for n in notes}}))
    c.check(any(big_numbers(s["statement"]) or re.search(r"billion", s["statement"], re.I)
                for s in statements(d)[:3]),
            "ilk 3 ifadede dünya nüfusu rakamı (milyar) var", "")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case7(ctx):
    c = Case(7)
    p = research("Will artificial intelligence replace programmers?", extra=["--lang", "en"], case=c)
    d = p.json()
    base_checks(c, p, d)
    if no_data(c, d):
        return c, p
    types = [s["claim_type"] for s in statements(d)]
    c.check("opinion" not in types, "görüş (opinion) cümlesi ifade olarak çıkmadı", f"türler: {types}")
    weak = [e for s in statements(d) for e in s["supporting"]
            if e["evidence_strength"] > 0.4 and s["claim_type"] == "forecast"]
    c.check(not weak, "tahmin (forecast) ifadelerinde kanıt gücü <= 0.40")
    c.info("claims_skipped_type", str((d or {}).get("stats", {}).get("claims_skipped_type")))
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case8(ctx):
    c = Case(8)
    p = research("How tall is the Eiffel Tower?", extra=["--agent", "--lang", "en"], case=c)
    d = p.json()
    base_checks(c, p, d)
    if no_data(c, d):
        return c, p
    tr = get_trace(p.run_id, c)
    if tr and "agent" in tr:
        ag = tr["agent"]
        c.check(bool(ag.get("stop_reason")), "durma nedeni kaydedilmiş", str(ag.get("stop_reason")))
        c.info("ajan adımı sayısı", str(len(ag.get("steps", []))))
        c.info("adımlar", "\n".join(short(json.dumps(s, ensure_ascii=False), 140) for s in ag.get("steps", [])[:12]))
    else:
        c.check(False, "ajan izi (trace.agent) kayıtlı", "audit çıktısında yok")
    if d:
        c.check(d["stats"].get("documents", 0) <= 16, "kaynak bütçesi (2 x max_sources) aşılmadı",
                f"documents={d['stats'].get('documents')}")
    c.info("ilk 5 ifade", "\n" + top_lines(d))
    return c, p


def case9(ctx):
    c = Case(9)
    if not ctx.get("case3_json") or not statements(ctx["case3_json"]):
        c.warn("vaka 3 sonuç üretmedi (ağ/kaynak sorunu); karşılaştırılacak bir şey yok, vaka atlandı")
        return c, None
    p = research("How tall is Mount Everest?", urls=EVEREST_URLS, extra=["--offline"], case=c)
    d, d1 = p.json(), ctx["case3_json"]
    base_checks(c, p, d)
    if d is not None:
        same = json.dumps(statements(d), sort_keys=True) == json.dumps(statements(d1), sort_keys=True)
        c.check(same, "--offline yeniden koşu, ilk koşuyla birebir aynı ifadeleri veriyor")
    rid = ctx.get("case3_run_id")
    if rid:
        a = run_dai(["audit", str(rid), "--format", "json"], c)
        try:
            stored = json.loads(a.out)
            c.check(json.dumps(statements(stored), sort_keys=True) == json.dumps(statements(d1), sort_keys=True),
                    "audit kaydı ilk koşuyla birebir aynı")
        except ValueError:
            c.check(False, "audit --format json geçerli JSON döndürdü")
        t = run_dai(["audit", str(rid), "--format", "text"], c)
        c.check(t.rc == 0 and ("evidence balance" in t.out or "kanıt dengesi" in t.out),
                "audit --format text okunabilir metin üretti")
    return c, p


def case10(ctx):
    c = Case(10)
    p = research("Mount Everest height", urls=["http://127.0.0.1:9/x"], case=c)
    c.check(p.rc in (1, 3) and no_traceback(p.out, p.err) and "blocked" in p.out + p.err
            and "robots" not in p.out + p.err, "özel adres (127.0.0.1) 'blocked' olarak reddedildi (robots değil)",
            f"çıkış kodu {p.rc}; {short(p.out + p.err, 160)}")
    p = research("Mount Everest height", urls=["https://www.dawn.com/news/0000000"], case=c)
    d = p.json()
    c.check(p.rc in (1, 3) and no_traceback(p.out, p.err), "404 sayfası uyarıyla geçildi (sahte-404 dahil)",
            short(" | ".join((d or {}).get("errors", [])), 160))
    p = research("Mount Everest height", urls=["ftp://example.com/x"], case=c)
    c.check(p.rc in (1, 3) and no_traceback(p.out, p.err) and "blocked" in p.out + p.err
            and "robots" not in p.out + p.err, "ftp:// adresi 'blocked: scheme' olarak reddedildi",
            f"çıkış kodu {p.rc}")
    p = research("xqzvk plorf zindle", extra=["--lang", "en"], case=c)
    c.check(p.rc in (1, 3) and no_traceback(p.out, p.err), "anlamsız soru: ifade yok, çökme yok", f"çıkış kodu {p.rc}")
    p = run_dai(["research", "   "], c)
    c.check(p.rc != 0 and no_traceback(p.out, p.err), "boş soru anlaşılır hatayla reddedildi",
            short(p.err, 140))
    return c, p


RUNNERS = {1: case1, 2: case2, 3: case3, 4: case4, 5: case5, 6: case6, 7: case7, 8: case8, 9: case9, 10: case10}


def extras() -> Case:
    c = Case(1)
    c.n, c.title = 0, "Ek: yardımcı komutlar (config, sources, trust, fetch, runs, cache)"
    steps = [(["config"], "config"), (["sources", "add", "example.org", "tier2"], "sources add"),
             (["sources", "list"], "sources list"), (["sources", "remove", "example.org"], "sources remove"),
             (["trust", BRIT], "trust"), (["fetch", BRIT, "--chars", "300"], "fetch"),
             (["runs", "--limit", "5"], "runs"), (["cache", "stats"], "cache stats")]
    for args, name in steps:
        p = run_dai(args, c)
        if p.rc != 0 and name in ("trust", "fetch") and "ERROR" in p.out:
            c.check(no_traceback(p.out, p.err), f"`{name}` çökmedi")
            c.warn(f"`{name}`: sayfa alınamadı", short(p.out + p.err, 160))
        else:
            c.check(p.rc == 0 and no_traceback(p.out, p.err), f"`{name}` çalıştı", f"çıkış kodu {p.rc}")
    return c


def write_report(cases: list[Case], outputs: dict):
    OUT.mkdir(exist_ok=True)
    L = ["# D-AI test bataryası raporu", "", f"Tarih: {time.strftime('%Y-%m-%d %H:%M')}  ",
         f"Python: {sys.version.split()[0]}", "",
         "| # | Vaka | PASS | FAIL | KNOWN | WARN | süre |", "|---|---|---|---|---|---|---|"]
    tot: dict = {}
    for c in cases:
        k = c.counts()
        for s, v in k.items():
            tot[s] = tot.get(s, 0) + v
        L.append(f"| {c.n or 'ek'} | {c.title} | {k.get('PASS', 0)} | {k.get('FAIL', 0)} | "
                 f"{k.get('KNOWN', 0)} | {k.get('WARN', 0)} | {c.seconds:.0f}s |")
    L += ["", f"**Toplam:** {tot}", "",
          "FAIL = bugün çalışması gereken şey bozuk. KNOWN = yol haritasında olan bilinen eksik (Pr3 başlangıç noktası). "
          "WARN = ağ/ortam sorunu, D-AI hakkında karar değil.", ""]
    for c in cases:
        L += [f"## Vaka {c.n or 'ek'}: {c.title}", ""]
        L += ["Komutlar:", "```"] + c.commands + ["```", ""]
        for s, name, det in c.checks:
            L.append(f"- **{s}** {name}" + (f": {det}" if det and "\n" not in det else ""))
            if det and "\n" in det:
                L += ["", "```", det.strip("\n"), "```"]
        L.append("")
    (OUT / "battery_report.md").write_text("\n".join(L), encoding="utf-8")
    for name, text in outputs.items():
        (OUT / name).write_text(text, encoding="utf-8")
    zp = ROOT / "battery_out.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in OUT.rglob("*"):
            if f.is_file() and "home" not in f.relative_to(OUT).parts[:1]:
                z.write(f, f.relative_to(ROOT))
    return zp, tot


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="D-AI live test battery")
    ap.add_argument("--only", type=int, nargs="+", help="run only these case numbers")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-extras", action="store_true")
    args = ap.parse_args()
    if args.list:
        for n, t in CASES.items():
            print(f"{n:2d}  {t}")
        return 0
    OUT.mkdir(exist_ok=True)
    HOME.mkdir(exist_ok=True)
    wanted = args.only or list(CASES)
    if 9 in wanted and 3 not in wanted:
        wanted = [3] + wanted
    ctx: dict = {}
    done: list[Case] = []
    outputs: dict = {}
    for n in sorted(set(wanted)):
        print(f"[{n}/10] {CASES[n]} ...", flush=True)
        try:
            c, p = RUNNERS[n](ctx)
        except Exception as e:      # the battery itself must never abort half-way
            c = Case(n)
            c.check(False, "betik hatası (D-AI değil, test betiği)", f"{type(e).__name__}: {e}")
            p = None
        if p is not None:
            outputs[f"case{n:02d}_stdout.txt"] = p.out
            outputs[f"case{n:02d}_stderr.txt"] = p.err
        k = c.counts()
        print(f"      PASS={k.get('PASS', 0)} FAIL={k.get('FAIL', 0)} KNOWN={k.get('KNOWN', 0)} "
              f"WARN={k.get('WARN', 0)}  ({c.seconds:.0f}s)", flush=True)
        done.append(c)
    if not args.no_extras and not args.only:
        print("[ek] yardımcı komutlar ...", flush=True)
        done.append(extras())
    zp, tot = write_report(done, outputs)
    print(f"\nRapor: {OUT / 'battery_report.md'}\nZip  : {zp}\nToplam: {tot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
