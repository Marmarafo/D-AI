"""D-AI command line interface (works in any terminal, incl. Termux and Windows)."""
from __future__ import annotations

import argparse
import json
import sys

from .. import __version__
from ..agents.planner import agent_research
from ..claims.segment import extract_claims
from ..config import load_config
from ..core.errors import DaiError
from ..core.pipeline import run_research
from ..extract.html_extract import extract_document
from ..ingest.fetch import Fetcher
from ..render.text_out import render_text
from ..storage.db import Database
from ..trust.score import score_source
from ..trust.tiers import normalize_domain

TIERS = ("tier1", "tier2", "tier3")


def _setup_streams() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _cfg(args, **extra):
    over = {k: v for k, v in extra.items() if v is not None}
    return load_config(overrides=over, path=getattr(args, "config", None))


def _open(args, **extra):
    cfg = _cfg(args, **extra)
    db = Database(cfg.resolved_db_path())
    if db.warning:
        print(f"warning: {db.warning}", file=sys.stderr)
    return cfg, db


def _fetch_doc(fetcher, url):
    raw = fetcher.fetch(url)
    if not raw.ok:
        return None, raw.error
    doc = extract_document(raw)
    if doc is None:
        return None, "no extractable text"
    return doc, None


def cmd_research(args) -> int:
    over = {"max_sources": args.max_sources, "offline": True if args.offline else None,
            "allow_private": True if args.allow_private else None,
            "providers": args.providers}
    cfg = _cfg(args, **over)
    db = Database(cfg.resolved_db_path())
    if db.warning:
        print(f"warning: {db.warning}", file=sys.stderr)
    try:
        fn = agent_research if args.agent else run_research
        result = fn(args.question, urls=args.url or [], cfg=cfg, db=db, lang=args.lang)
    finally:
        db.close()
    if args.json:
        print(result.json())
    else:
        print(result.text())
    if args.trace:
        print(json.dumps(result.trace, ensure_ascii=False, indent=2), file=sys.stderr)
    if result.run_id:
        print(f"\n(run id: {result.run_id}; inspect with: dai audit {result.run_id})", file=sys.stderr)
    return 0 if result.statements else 3


def cmd_fetch(args) -> int:
    cfg, db = _open(args, allow_private=True if args.allow_private else None)
    rc = 0
    with db:
        f = Fetcher(cfg, db)
        for u in args.url:
            doc, err = _fetch_doc(f, u)
            if err:
                print(f"{u}: ERROR {err}")
                rc = 1
                continue
            print(f"== {doc.url} ==")
            print(f"title    : {doc.title}")
            print(f"author   : {doc.author}")
            print(f"published: {doc.published}")
            print(f"language : {doc.language}")
            print(f"chars    : {len(doc.text)}  words: {doc.word_count}")
            print(doc.text[:args.chars])
            print()
    return rc


def cmd_claims(args) -> int:
    cfg, db = _open(args, allow_private=True if args.allow_private else None)
    rc = 0
    with db:
        f = Fetcher(cfg, db)
        for u in args.url:
            doc, err = _fetch_doc(f, u)
            if err:
                print(f"{u}: ERROR {err}")
                rc = 1
                continue
            print(f"== {doc.url} ==")
            for i, c in enumerate(extract_claims(doc.text, doc.url, doc.language,
                                                 args.limit), 1):
                print(f"{i:2d}. [{c.claim_type:9s}] {c.text}")
                print(f"     subj={c.subject!r} pred={c.predicate!r} nums={list(c.numbers)} "
                      f"dates={list(c.dates)} negated={c.negated}")
            print()
    return rc


def cmd_trust(args) -> int:
    cfg, db = _open(args, allow_private=True if args.allow_private else None)
    rc = 0
    with db:
        f = Fetcher(cfg, db)
        tiers = db.tier_map()
        for u in args.url:
            doc, err = _fetch_doc(f, u)
            if err:
                print(f"{u}: ERROR {err}")
                rc = 1
                continue
            r = score_source(doc.url, doc, tiers)
            print(f"{doc.url} -> {r.score * 100:.0f}/100 (tier: {r.tier})")
            for k, v in r.subscores.items():
                print(f"    {k:11s} {v:.2f}")
            for s in r.signals:
                print(f"    * {s}")
    return rc


def cmd_sources(args) -> int:
    _cfg_, db = _open(args)
    with db:
        if args.action == "list":
            rows = db.list_tiers()
            if not rows:
                print("no custom tier entries")
            for r in rows:
                print(f"{r['tier']:6s} {r['domain']}")
        elif args.action == "add":
            d = normalize_domain(args.domain)
            db.set_tier(d, args.tier)
            print(f"{d} -> {args.tier}")
        else:
            print("removed" if db.remove_tier(normalize_domain(args.domain)) else "not found")
    return 0


def cmd_audit(args) -> int:
    _cfg_, db = _open(args)
    with db:
        run = db.get_run(args.run_id)
    if run is None:
        print(f"run {args.run_id} not found", file=sys.stderr)
        return 1
    if args.format == "text":
        print(render_text(run["result"]))
    elif args.format == "json":
        print(json.dumps(run["result"], ensure_ascii=False, indent=2))
    elif args.format == "trace":
        print(json.dumps(run["trace"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps({k: run[k] for k in ("id", "question", "lang", "started", "finished",
                                              "config", "stats", "errors")},
                         ensure_ascii=False, indent=2))
    return 0


def cmd_runs(args) -> int:
    _cfg_, db = _open(args)
    with db:
        for r in db.list_runs(args.limit):
            print(f"{r['id']:5d}  {r['question']}")
    return 0


def cmd_cache(args) -> int:
    _cfg_, db = _open(args)
    with db:
        if args.action == "stats":
            s = db.cache_stats()
            print(f"pages: {s['pages']}  bytes: {s['bytes']}")
        else:
            older = args.older_than_days * 86400 if args.older_than_days else None
            print(f"removed {db.clear_cache(older)} pages")
    return 0


def cmd_config(args) -> int:
    cfg = _cfg(args)
    print(json.dumps(cfg.snapshot(), ensure_ascii=False, indent=2))
    print(f"\ndatabase: {cfg.resolved_db_path()}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dai", description="D-AI: algorithmic multi-source research (not an LLM)")
    p.add_argument("--config", help="path to a config.toml")
    p.add_argument("-V", "--version", action="version", version=f"dai {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("research", help="research a question")
    r.add_argument("question")
    r.add_argument("--url", action="append", help="source URL (repeatable); skips search")
    r.add_argument("--agent", action="store_true", help="deterministic research agent")
    r.add_argument("--json", action="store_true", help="JSON output")
    r.add_argument("--max-sources", type=int, default=None)
    r.add_argument("--offline", action="store_true", help="use cached pages only")
    r.add_argument("--lang", choices=["en", "tr"], default=None, help="question language")
    r.add_argument("--providers", default=None, help="comma list: wikipedia,searxng,brave")
    r.add_argument("--allow-private", action="store_true",
                   help="allow localhost/private addresses (development only)")
    r.add_argument("--trace", action="store_true", help="print the analysis trace to stderr")
    r.set_defaults(func=cmd_research)

    for name, fn, helptext in (("fetch", cmd_fetch, "fetch and extract article text"),
                               ("claims", cmd_claims, "extract claims from URLs"),
                               ("trust", cmd_trust, "score source reliability")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("url", nargs="+")
        sp.add_argument("--allow-private", action="store_true")
        if name == "fetch":
            sp.add_argument("--chars", type=int, default=3000)
        if name == "claims":
            sp.add_argument("--limit", type=int, default=80)
        sp.set_defaults(func=fn)

    s = sub.add_parser("sources", help="manage reputation tiers")
    ssub = s.add_subparsers(dest="action", required=True)
    ssub.add_parser("list")
    sa = ssub.add_parser("add")
    sa.add_argument("domain")
    sa.add_argument("tier", choices=TIERS)
    sr = ssub.add_parser("remove")
    sr.add_argument("domain")
    s.set_defaults(func=cmd_sources)

    a = sub.add_parser("audit", help="inspect a stored run")
    a.add_argument("run_id", type=int)
    a.add_argument("--format", choices=["summary", "text", "json", "trace"], default="summary")
    a.set_defaults(func=cmd_audit)

    ru = sub.add_parser("runs", help="list recent runs")
    ru.add_argument("--limit", type=int, default=20)
    ru.set_defaults(func=cmd_runs)

    c = sub.add_parser("cache", help="page cache")
    c.add_argument("action", choices=["stats", "clear"])
    c.add_argument("--older-than-days", type=float, default=None)
    c.set_defaults(func=cmd_cache)

    cf = sub.add_parser("config", help="show effective configuration")
    cf.set_defaults(func=cmd_config)
    return p


def main(argv=None) -> int:
    _setup_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DaiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
