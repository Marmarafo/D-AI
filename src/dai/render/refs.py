"""Shared reference registry: one number per canonical URL."""
from __future__ import annotations

from ..ingest.urls import url_key


class RefRegistry:
    def __init__(self):
        self.refs: list[dict] = []
        self._index: dict[str, int] = {}

    def add(self, url: str, title: str = "", trust: float | None = None,
            domain: str = "", published: str | None = None) -> int:
        k = url_key(url)
        if k not in self._index:
            self._index[k] = len(self.refs) + 1
            self.refs.append({"ref": len(self.refs) + 1, "url": url, "title": title or "",
                              "source_reliability": round(trust, 3) if trust is not None else None,
                              "domain": domain, "published": published})
        return self._index[k]
