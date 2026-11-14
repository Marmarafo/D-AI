"""Structured JSON output (schema dai.result/1). Built first; text is derived from it."""
from __future__ import annotations

import json

from .refs import RefRegistry

SCHEMA = "dai.result/2"   # /2: source_reliability, evidence_strength, evidence_balance


def _ev(reg: RefRegistry, e) -> dict:
    n = reg.add(e.url, e.title, e.reliability, e.domain, e.published)
    return {"ref": n, "url": e.url, "title": e.title, "domain": e.domain, "quote": e.quote,
            "source_reliability": round(e.reliability, 3),
            "evidence_strength": round(e.strength, 3),
            "strength_signals": list(e.strength_signals), "published": e.published}


def _note(n: tuple) -> dict:
    return {"code": n[0], "args": list(n[1:])}


def result_to_dict(result) -> dict:
    reg = RefRegistry()
    sts = []
    for s in result.statements:
        sts.append({
            "statement": s.text, "claim_type": s.claim_type, "status": s.status,
            "evidence_balance": round(s.balance, 3), "relevance": round(s.relevance, 3),
            "independent_sources": s.independent_sources, "cluster_size": s.cluster_size,
            "supporting": [_ev(reg, e) for e in s.supporting],
            "dissent": [_ev(reg, e) for e in s.dissent],
            "notes": [_note(n) for n in s.notes],
        })
    stats = {k: v for k, v in result.stats.items()}
    return {"schema": SCHEMA, "query": result.question, "language": result.language,
            "output_language": result.output_language, "stats": stats, "statements": sts,
            "references": reg.refs, "errors": list(result.errors)}


def render_json(result) -> str:
    return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
