"""Research pipeline: discover -> ingest -> extract -> claims -> trust -> analyze -> synthesize."""
from __future__ import annotations

import time
from dataclasses import replace

from ..analysis.cluster import analyze as analyze_clusters
from ..analysis.independence import group_documents
import re

from ..claims.question import profile_question, rank_results, search_queries
from ..claims.relevance import question_terms, score_claims
from ..claims.segment import extract_claims
from ..config import Config
from ..core.errors import ConfigError
from ..core.models import Document, ResearchResult
from ..discovery.providers import build_providers
from ..extract.html_extract import extract_document
from ..i18n.tokenize import content_stems, detect_language
from ..ingest.fetch import Fetcher
from ..ingest.urls import url_key
from ..storage.db import Database
from ..synthesis.aggregate import synthesize
from ..trust.score import score_source


_ERR_TITLE = re.compile(
    r"(?i)\b(?:404|page not found|not found|bulunamad\w*|sayfa yok|error|hata|access denied|"
    r"forbidden|no longer available|artık mevcut değil)\b")


def looks_like_error_page(doc: Document) -> bool:
    """A short page whose title says "not found": servers often answer such pages with HTTP 200."""
    return bool(_ERR_TITLE.search(doc.title or "")) and len(doc.text) < 1500


class ResearchSession:
    """Stateful research over one question; stages are callable separately (agent uses this)."""

    def __init__(self, question: str, cfg: Config, db: Database | None = None, fetcher=None,
                 providers=None, lang: str | None = None, max_docs: int | None = None):
        self.question = question.strip()
        self.cfg = cfg
        self.db = db
        self.fetcher = fetcher or Fetcher(cfg, db)
        self._providers = providers
        self.lang = lang or detect_language(self.question, cfg.default_language)
        self.out_lang = self.lang if cfg.output_language == "auto" else cfg.output_language
        self.profile = profile_question(self.question, self.lang)
        self.max_docs = max_docs or cfg.max_sources
        self.docs: dict[str, Document] = {}
        self.errors: list[str] = []
        self.seen: set[str] = set()
        self.fetch_attempted = 0
        self.fetch_failed = 0
        self._claims: dict[str, list] = {}
        self.timing: dict[str, float] = {}

    @property
    def providers(self):
        if self._providers is None:
            self._providers = build_providers(self.cfg)
        return self._providers

    @property
    def budget_left(self) -> int:
        return self.max_docs - len(self.docs)

    # ---- discovery
    def discover(self, query: str | None = None, limit: int | None = None) -> list[str]:
        """Search every provider and return URLs best-title-match first.

        For the question itself the search runs on short queries (content words, bare names),
        because a full sentence makes search engines return pages that merely share a word.
        """
        queries = [query] if query else search_queries(self.question, self.lang)
        limit = limit or self.max_docs * 2
        results_all: list = []
        keys: set[str] = set()
        failed: set[str] = set()
        for q in queries:
            for p in self.providers:
                if p.name in failed:
                    continue
                try:
                    results = p.search(q, limit, self.lang)
                except Exception as e:  # provider failures must not abort research
                    self.errors.append(f"search provider {p.name}: {e}")
                    failed.add(p.name)
                    continue
                for r in results:
                    k = url_key(r.url)
                    if k not in keys and k not in self.seen:
                        keys.add(k)
                        results_all.append(r)
        ranked = rank_results(results_all, query or self.question, self.lang)
        return [r.url for r in ranked][:limit]

    # ---- ingestion
    def ingest(self, urls: list[str]) -> list[Document]:
        t0 = time.perf_counter()
        pending = []
        for u in urls:
            k = url_key(u)
            if k not in self.seen:
                self.seen.add(k)
                pending.append(u)
        added: list[Document] = []
        while pending and self.budget_left > 0:
            batch, pending = pending[:self.budget_left], pending[self.budget_left:]
            pages = self.fetcher.fetch_many(batch)
            for u, page in zip(batch, pages):
                self.fetch_attempted += 1
                if not page.ok:
                    self.fetch_failed += 1
                    self.errors.append(f"{u}: {page.error}")
                    continue
                doc = extract_document(page)
                if doc is None or len(doc.text) < self.cfg.min_doc_chars:
                    self.fetch_failed += 1
                    self.errors.append(f"{u}: too little extractable text")
                    continue
                if looks_like_error_page(doc):
                    self.fetch_failed += 1
                    self.errors.append(f"{u}: looks like an error page (soft 404), skipped")
                    continue
                dk = url_key(doc.url)
                self.seen.add(dk)
                if dk in self.docs:
                    continue
                self.docs[dk] = doc
                added.append(doc)
        self.timing["ingest"] = self.timing.get("ingest", 0.0) + time.perf_counter() - t0
        return added

    def _could_be_relevant(self, doc_lang: str):
        # not prop_stems: words like "long"/"high" appear in sentences that have nothing to do with it
        wanted = question_terms(self.question, self.lang) | self.profile.entity_stems
        if not wanted:
            return None

        def keep(sentence: str) -> bool:
            return bool(re.search(r"\d", sentence)) or bool(content_stems(sentence, doc_lang) & wanted)
        return keep

    @staticmethod
    def _cap_per_doc(claims: list, limit: int) -> list:
        by_doc: dict[str, list] = {}
        for c in claims:
            by_doc.setdefault(c.doc_url, []).append(c)
        out = []
        for lst in by_doc.values():
            lst.sort(key=lambda c: (-c.relevance, c.start))
            out.extend(lst[:limit])
        return out

    # ---- analysis
    def analyze(self) -> ResearchResult:
        t0 = time.perf_counter()
        cfg = self.cfg
        docs = sorted(self.docs.values(), key=lambda d: d.url)
        user_tiers = self.db.tier_map() if self.db else {}
        by_url = {d.url: d for d in docs}
        trust = {d.url: score_source(d.url, d, user_tiers) for d in docs}

        all_claims = []
        for d in docs:
            if d.url not in self._claims:
                # Capping at the first N sentences used to drop the one sentence that held the
                # answer. Instead: skip sentences that cannot be relevant (no digit and none of
                # the question's words), extract the rest generously, cap by relevance later.
                self._claims[d.url] = extract_claims(d.text, d.url, d.language,
                                                     cfg.max_claims_per_doc * 4,
                                                     keep=self._could_be_relevant(d.language))
            all_claims.extend(self._claims[d.url])
        typed = [c for c in all_claims if c.claim_type in cfg.include_types]
        topics = {d.url: content_stems(d.title or "", d.language) for d in docs}
        relevant = score_claims(typed, question_terms(self.question, self.lang), cfg.min_relevance,
                                self.profile, topics, self.lang)
        relevant = self._cap_per_doc(relevant, cfg.max_claims_per_doc)
        if len(relevant) > cfg.max_claims:
            relevant = sorted(relevant, key=lambda c: (-c.relevance, -trust[c.doc_url].score,
                                                       c.doc_url, c.start))[:cfg.max_claims]
        relevant.sort(key=lambda c: (c.doc_url, c.start))

        clusters = analyze_clusters(relevant, cfg)
        groups = group_documents(docs, cfg.dup_j) if docs else {}
        statements = synthesize(relevant, clusters, by_url, trust, groups, cfg, self.profile)
        if docs and not statements:
            langs = {d.language for d in docs}
            if self.lang not in langs:
                self.errors.append(
                    f"question language is {self.lang!r} but the sources are {sorted(langs)}: "
                    "claims in another language are not compared; ask in the sources' language "
                    "or pass --lang")

        stats = {
            "sources_attempted": self.fetch_attempted, "sources_failed": self.fetch_failed,
            "documents": len(docs), "independent_groups": len(set(groups.values())),
            "claims_total": len(all_claims),
            "claims_skipped_type": len(all_claims) - len(typed),
            "claims_relevant": len(relevant), "clusters": len(clusters),
            "statements": len(statements),
        }
        trace = {
            "documents": [{
                "url": d.url, "title": d.title, "domain": d.domain, "language": d.language,
                "published": d.published, "group": groups.get(d.url),
                "trust": {"score": trust[d.url].score, "tier": trust[d.url].tier,
                          "subscores": trust[d.url].subscores, "signals": list(trust[d.url].signals)},
                "claims": len(self._claims.get(d.url, []))} for d in docs],
            "clusters": [{
                "key": cl.key,
                "members": [{"index": i, "doc": relevant[i].doc_url, "text": relevant[i].text}
                            for i in cl.members],
                "relations": [{"a": r.a, "b": r.b, "kind": r.kind, "signals": r.signals}
                              for r in cl.relations]} for cl in clusters],
        }
        self.timing["analyze"] = time.perf_counter() - t0
        trace["timing_s"] = {k: round(v, 3) for k, v in self.timing.items()}
        return ResearchResult(question=self.question, language=self.lang,
                              output_language=self.out_lang, statements=statements,
                              stats=stats, errors=list(self.errors), trace=trace)


def record_run(db: Database, session: ResearchSession, result: ResearchResult, run_id: int) -> None:
    db.finish_run(run_id, result.stats, result.errors, result.to_dict(), result.trace)
    result.run_id = run_id


def run_research(question: str, urls=(), cfg: Config | None = None, db: Database | None = None,
                 fetcher=None, providers=None, lang: str | None = None,
                 record: bool = True) -> ResearchResult:
    cfg = cfg or Config()
    if not question.strip():
        raise ConfigError("question must not be empty")
    own_db = db is None
    if own_db:
        db = Database(cfg.resolved_db_path())
    try:
        s = ResearchSession(question, cfg, db, fetcher, providers, lang)
        run_id = db.create_run(s.question, s.lang, cfg.snapshot()) if record else None
        if urls:
            s.ingest(list(urls))
        else:
            found = s.discover()
            if not found:
                s.errors.append("no sources found (no results from search providers; "
                                "pass --url or configure a provider)")
            s.ingest(found)
        result = s.analyze()
        if record and run_id is not None:
            record_run(db, s, result, run_id)
        return result
    finally:
        if own_db:
            db.close()
