"""HTML -> Document using only html.parser (no lxml): main text + metadata."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from ..core.models import Document, RawPage
from ..claims.normalize import extract_dates
from ..i18n.tokenize import detect_language, fold
from ..ingest.urls import host_of, registered_domain

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "nav", "footer", "aside",
             "form", "button", "select", "option", "menu", "dialog", "canvas"}
NEVER_SKIP = {"html", "body", "main", "article", "head", "title"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "blockquote", "h1", "h2",
              "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "table", "figure", "figcaption",
              "pre", "header", "dd", "dt", "dl", "hr"}
HINT_TOKENS = {"comment", "comments", "sidebar", "footer", "nav", "navbar", "menu", "share",
               "sharing", "social", "promo", "advert", "advertisement", "ads", "ad", "related",
               "cookie", "cookies", "newsletter", "subscribe", "breadcrumb", "breadcrumbs",
               "widget", "popup", "modal", "toolbar"}
SKIP_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
BOILER = re.compile(
    r"(?i)(?:\b(?:cookies?|çerez\w*|all rights reserved|tüm hakları saklıdır|subscribe|newsletter|"
    r"sign up|log ?in|follow us|share this|advertisement|reklam|abone ol|privacy policy|"
    r"gizlilik politikası|terms of (?:use|service)|read more|devamını oku|click here|"
    r"yorum yap)\b|©)")


class _Block:
    __slots__ = ("text", "link_chars", "container", "kind")

    def __init__(self, text, link_chars, container, kind):
        self.text, self.link_chars, self.container, self.kind = text, link_chars, container, kind


class _Parser(HTMLParser):
    def __init__(self, page_host: str):
        super().__init__(convert_charrefs=True)
        self.page_host = page_host
        self.stack: list[dict] = []
        self.blocks: list[_Block] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self.h1: list[str] = []
        self.lang = ""
        self.canonical = ""
        self.time_dt: list[tuple[str, bool]] = []
        self.ld: list[dict] = []
        self.author_dom = ""
        self.external = 0
        self._skip = 0
        self._buf: list[str] = []
        self._link_chars = 0
        self._a = 0
        self._kind = "o"
        self._cseq = 0
        self._cstack: list[int] = []
        self._title_buf: list[str] = []
        self._ld_buf: list[str] = []
        self._author_buf: list[str] = []

    # ---- helpers
    def _hinted(self, a: dict) -> bool:
        if a.get("hidden") is not None or a.get("aria-hidden", "").lower() == "true":
            return True
        if a.get("role", "").lower() in SKIP_ROLES:
            return True
        if "display:none" in a.get("style", "").replace(" ", "").lower():
            return True
        toks = set(re.split(r"[^a-z0-9]+", (a.get("class", "") + " " + a.get("id", "")).lower()))
        return bool(toks & HINT_TOKENS)

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        if text and not self._skip:
            self.blocks.append(_Block(text, self._link_chars,
                                      self._cstack[-1] if self._cstack else 0, self._kind))
        self._buf, self._link_chars = [], 0

    # ---- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
            return
        if tag == "link":
            if "canonical" in a.get("rel", "").lower() and not self.canonical:
                self.canonical = a.get("href", "")
            return
        if tag in VOID:
            if tag == "br" and not self._skip:
                self._flush()
            return
        if tag == "p" and self.stack and self.stack[-1]["tag"] == "p":
            self.handle_endtag("p")
        skip = tag in SKIP_TAGS or (tag not in NEVER_SKIP and self._hinted(a))
        frame = {"tag": tag, "skip": skip}
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            frame["ld"] = True
            frame["skip"] = True
        self.stack.append(frame)
        if frame["skip"]:
            self._skip += 1
            return
        if tag == "title":
            frame["title"] = True
        if tag in BLOCK_TAGS:
            self._flush()
            if tag in ("article", "main"):
                self._cseq += 1
                frame["cid"] = self._cseq
                self._cstack.append(self._cseq)
            self._kind = "h" if tag in ("h1", "h2", "h3", "h4", "h5", "h6") else \
                "li" if tag == "li" else "p" if tag in ("p", "blockquote") else "o"
            if tag == "h1":
                frame["h1"] = True
        if tag == "a":
            frame["a"] = True
            self._a += 1
            href = a.get("href", "")
            if href.startswith(("http://", "https://")):
                h = host_of(href)
                if h and registered_domain(h) != registered_domain(self.page_host):
                    self.external += 1
        if tag == "time" and a.get("datetime"):
            self.time_dt.append((a["datetime"], bool(self._cstack)))
        toks = set(re.split(r"[^a-z0-9]+", (a.get("class", "") + " " + a.get("rel", "")).lower()))
        if (a.get("itemprop", "").lower() == "author" or "author" in toks or "byline" in toks) \
                and not self.author_dom and not self._author_buf:
            frame["author"] = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                idx = i
                break
        if idx is None:
            return
        while len(self.stack) > idx:
            self._close(self.stack.pop())

    def _close(self, f: dict):
        tag = f["tag"]
        if f.get("ld"):
            self._parse_ld("".join(self._ld_buf))
            self._ld_buf = []
        if f["skip"]:
            self._skip -= 1
            return
        if f.get("title"):
            self.title = " ".join("".join(self._title_buf).split())
            self._title_buf = []
        if f.get("a"):
            self._a -= 1
        if f.get("author"):
            txt = " ".join("".join(self._author_buf).split())
            self._author_buf = []
            if 1 < len(txt) <= 80 and not self.author_dom:
                self.author_dom = re.sub(r"(?i)^(by|yazan|yazar|haber:?)\s+", "", txt)
        if tag in BLOCK_TAGS:
            if f.get("h1") and self._buf:
                self.h1.append(" ".join("".join(self._buf).split()))
            self._flush()
            if f.get("cid"):
                self._cstack.pop()
            self._kind = "o"

    def handle_data(self, data):
        top = self.stack[-1] if self.stack else None
        if top is not None and top.get("ld"):
            self._ld_buf.append(data)
            return
        if self._skip:
            return
        if any(f.get("title") for f in self.stack[-2:]):
            self._title_buf.append(data)
            return
        self._buf.append(data)
        if self._a:
            self._link_chars += len(data)
        if any(f.get("author") for f in self.stack):
            self._author_buf.append(data)

    def _parse_ld(self, raw: str):
        try:
            data = json.loads(raw)
        except ValueError:
            return
        items = data if isinstance(data, list) else data.get("@graph", [data]) \
            if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict):
                self.ld.append(it)

    def close(self):
        super().close()
        self._flush()


def decode_body(body: bytes, content_type: str = "") -> str:
    enc = None
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        enc = m.group(1)
    else:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    for cand in ([enc] if enc else []) + ["utf-8", "cp1254", "latin-1"]:
        try:
            return body.decode(cand)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _ld_first(ld: list[dict], key: str):
    for it in ld:
        if key in it:
            return it[key]
    return None


def _name(v) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return str(v.get("name", "")).strip()
    if isinstance(v, list) and v:
        return _name(v[0])
    return ""


def _iso_date(s: str | None) -> str | None:
    if not s:
        return None
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    dates, _ = extract_dates(fold(s))
    return dates[0] if dates else None


def _select_main(blocks: list[_Block]) -> list[str]:
    containers: dict[int, int] = {}
    for b in blocks:
        if b.container:
            containers[b.container] = containers.get(b.container, 0) + len(b.text)
    pool = blocks
    if containers:
        best, size = max(containers.items(), key=lambda kv: kv[1])
        if size >= 200:
            pool = [b for b in blocks if b.container == best]
    out, last = [], None
    for b in pool:
        t = b.text
        if b.kind == "h":
            continue
        if len(t) < 25 and not t.endswith((".", "!", "?")):
            continue
        if b.link_chars / max(1, len(t)) > 0.6:
            continue
        if len(t) < 160 and BOILER.search(t):
            continue
        if b.kind == "li" and len(t) < 40:
            continue
        if t == last:
            continue
        out.append(t)
        last = t
    return out


def extract_document(raw: RawPage) -> Document | None:
    final = raw.final_url or raw.url
    host = host_of(final)
    ctype = raw.content_type.lower()
    html = decode_body(raw.body, raw.content_type)
    if "text/plain" in ctype:
        paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", html) if p.strip()]
        text = "\n\n".join(paras)
        return Document(url=final, domain=registered_domain(host), title=paras[0][:120] if paras else "",
                        language=detect_language(text), text=text, word_count=len(text.split()),
                        fetched_at=raw.fetched_at)
    p = _Parser(host)
    try:
        p.feed(html)
        p.close()
    except Exception:  # html.parser can raise on pathological input
        pass
    paras = _select_main(p.blocks)
    desc = p.meta.get("og:description") or p.meta.get("description") or ""
    text = "\n\n".join(paras)
    if len(text) < 200 and desc:
        text = (desc + "\n\n" + text).strip()
    if not text:
        return None
    meta = p.meta
    ld = p.ld
    title = (meta.get("og:title") or _name(_ld_first(ld, "headline")) or p.title
             or (p.h1[0] if p.h1 else ""))
    author = (meta.get("author") or meta.get("article:author") or meta.get("twitter:creator")
              or _name(_ld_first(ld, "author")) or p.author_dom)
    if author.startswith(("http://", "https://")):
        author = _name(_ld_first(ld, "author")) or p.author_dom
    published = _iso_date(meta.get("article:published_time") or meta.get("og:article:published_time")
                          or _name(_ld_first(ld, "datePublished")) or meta.get("datepublished")
                          or meta.get("date") or meta.get("pubdate")
                          or next((d for d, inside in p.time_dt if inside), None)
                          or (p.time_dt[0][0] if p.time_dt else None))
    publisher = meta.get("og:site_name") or _name(_ld_first(ld, "publisher"))
    lang = (p.lang or "")[:2].lower()
    detected = detect_language(text, default=lang if lang in ("en", "tr") else "en")
    return Document(
        url=final, domain=registered_domain(host), title=title.strip(), author=author.strip()[:80],
        publisher=publisher.strip(), published=published, language=detected, text=text,
        word_count=len(text.split()), external_links=p.external, canonical_url=p.canonical,
        fetched_at=raw.fetched_at)
