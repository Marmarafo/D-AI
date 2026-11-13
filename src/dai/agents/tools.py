"""Tool interface for the deterministic research agent (every call is logged)."""
from __future__ import annotations

from ..core.pipeline import ResearchSession
from ..i18n.tokenize import content_tokens, tokens


def keywords(text: str, lang: str, limit: int = 6) -> list[str]:
    seen, out = set(), []
    for t in content_tokens(text, lang):
        if t not in seen and not t.isdigit():
            seen.add(t)
            out.append(t)
    return out[:limit]


class ToolBox:
    def __init__(self, session: ResearchSession):
        self.s = session
        self.log: list[dict] = []

    def call(self, name: str, **kw):
        out = getattr(self, "tool_" + name)(**kw)
        summary = (f"{len(out)} items" if isinstance(out, list) else
                   out if isinstance(out, (int, str)) else "ok")
        self.log.append({"step": len(self.log) + 1, "tool": name,
                         "args": {k: (len(v) if isinstance(v, (list, tuple)) else
                                     v if isinstance(v, (str, int, float, bool)) else type(v).__name__)
                                 for k, v in kw.items()},
                         "result": summary})
        return out

    def tool_search(self, query: str) -> list[str]:
        return self.s.discover(query)

    def tool_fetch(self, urls: list[str]) -> int:
        return len(self.s.ingest(urls))

    def tool_analyze(self):
        return self.s.analyze()

    def tool_expand(self, reasons: list[str], result) -> list[str]:
        lang = self.s.lang
        kw = keywords(self.s.question, lang)
        suffix = "resmi açıklama" if lang == "tr" else "official statement"
        out: list[str] = []
        if "disputed" in reasons:
            for st in result.statements:
                if st.status in ("disputed", "mixed"):
                    k = keywords(st.text, lang, 6)
                    if k:
                        out.append(" ".join(k) + " " + suffix)
                    break
        if "thin" in reasons or "no_statements" in reasons:
            if kw:
                out.append(" ".join(kw))
                out.append(" ".join(kw[:4]) + " " + suffix)
        return [q for q in dict.fromkeys(out) if q.strip()]
