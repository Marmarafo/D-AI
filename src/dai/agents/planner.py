"""Deterministic research agent: planner + tools + budget + stop rule (no LLM)."""
from __future__ import annotations

from ..config import Config
from ..core.errors import ConfigError
from ..core.models import ResearchResult
from ..core.pipeline import ResearchSession, record_run
from ..storage.db import Database
from .tools import ToolBox


def evaluate(result: ResearchResult, cfg: Config) -> list[str]:
    reasons = []
    if not result.statements:
        reasons.append("no_statements")
    if result.stats.get("independent_groups", 0) < cfg.agent_min_independent:
        reasons.append("thin")
    if any(s.status in ("disputed", "mixed") for s in result.statements):
        reasons.append("disputed")
    return reasons


def agent_research(question: str, cfg: Config | None = None, db: Database | None = None,
                   urls=(), fetcher=None, providers=None, lang: str | None = None,
                   record: bool = True) -> ResearchResult:
    cfg = cfg or Config()
    if not question.strip():
        raise ConfigError("question must not be empty")
    own_db = db is None
    if own_db:
        db = Database(cfg.resolved_db_path())
    try:
        s = ResearchSession(question, cfg, db, fetcher, providers, lang,
                            max_docs=cfg.max_sources * 2)
        run_id = db.create_run(s.question, s.lang, cfg.snapshot()) if record else None
        tb = ToolBox(s)
        done_queries = {question.strip().lower()}

        per_round = cfg.max_sources
        if urls:
            tb.call("fetch", urls=list(urls), limit=per_round)
        else:
            tb.call("fetch", urls=tb.call("search"), limit=per_round)
        result = tb.call("analyze")
        stop = "rounds exhausted"
        for _ in range(1, cfg.agent_rounds):
            reasons = evaluate(result, cfg)
            if not reasons:
                stop = "goals met"
                break
            if s.budget_left <= 0:
                stop = "source budget exhausted"
                break
            queries = [q for q in tb.call("expand", reasons=reasons, result=result)
                       if q.lower() not in done_queries][:2]
            if not queries:
                stop = "no new queries"
                break
            new_urls: list[str] = []
            for q in queries:
                done_queries.add(q.lower())
                new_urls += tb.call("search", query=q)
            if tb.call("fetch", urls=new_urls, limit=per_round) == 0:
                stop = "no new sources"
                break
            result = tb.call("analyze")
        got = result.stats.get("independent_groups", 0)
        if got < cfg.agent_min_independent:
            result.errors.append(
                f"only {got} independent source group(s) found, wanted {cfg.agent_min_independent}: "
                "pages from one publisher count once; add a provider (searxng/brave) or --url")
        result.trace["agent"] = {"steps": tb.log, "stop_reason": stop}
        result.stats["agent_steps"] = len(tb.log)
        if record and run_id is not None:
            record_run(db, s, result, run_id)
        return result
    finally:
        if own_db:
            db.close()
