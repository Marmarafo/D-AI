"""Search providers: Wikipedia (no key), SearxNG (self-hosted), Brave (API key)."""
from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from ..core.errors import ConfigError, FetchError
from ..ingest.http import http_get
from .base import SearchResult


def _get_json(url: str, cfg, headers: dict | None = None):
    r = http_get(url, cfg, headers={"Accept": "application/json", **(headers or {})})
    if r.status != 200:
        raise FetchError(f"HTTP {r.status} from search provider")
    try:
        return json.loads(r.body.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise FetchError(f"search provider returned invalid JSON: {e}") from e


class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, cfg):
        self.cfg = cfg

    def search(self, query: str, limit: int, lang: str = "en") -> list[SearchResult]:
        host = f"https://{'tr' if lang == 'tr' else 'en'}.wikipedia.org"
        q = urlencode({"action": "query", "list": "search", "srsearch": query,
                       "srlimit": limit, "format": "json", "utf8": 1})
        data = _get_json(f"{host}/w/api.php?{q}", self.cfg)
        out = []
        for it in data.get("query", {}).get("search", []):
            title = it.get("title", "")
            if title:
                out.append(SearchResult(url=f"{host}/wiki/{quote(title.replace(' ', '_'))}",
                                        title=title, snippet=it.get("snippet", "")))
        return out


class SearxngProvider:
    name = "searxng"

    def __init__(self, cfg):
        if not cfg.searxng_url:
            raise ConfigError("searxng provider needs 'searxng_url' (JSON format must be enabled)")
        self.cfg = cfg

    def search(self, query: str, limit: int, lang: str = "en") -> list[SearchResult]:
        q = urlencode({"q": query, "format": "json", "language": lang})
        data = _get_json(f"{self.cfg.searxng_url.rstrip('/')}/search?{q}", self.cfg)
        return [SearchResult(url=r["url"], title=r.get("title", ""), snippet=r.get("content", ""))
                for r in data.get("results", [])[:limit] if r.get("url")]


class BraveProvider:
    name = "brave"

    def __init__(self, cfg):
        if not cfg.brave_key:
            raise ConfigError("brave provider needs an API key (BRAVE_API_KEY or brave_key)")
        self.cfg = cfg

    def search(self, query: str, limit: int, lang: str = "en") -> list[SearchResult]:
        q = urlencode({"q": query, "count": min(limit, 20), "search_lang": lang})
        data = _get_json(f"https://api.search.brave.com/res/v1/web/search?{q}", self.cfg,
                         headers={"X-Subscription-Token": self.cfg.brave_key})
        return [SearchResult(url=r["url"], title=r.get("title", ""), snippet=r.get("description", ""))
                for r in data.get("web", {}).get("results", [])[:limit] if r.get("url")]


REGISTRY = {"wikipedia": WikipediaProvider, "searxng": SearxngProvider, "brave": BraveProvider}


def build_providers(cfg) -> list:
    out = []
    for name in cfg.providers:
        cls = REGISTRY.get(name)
        if cls is None:
            raise ConfigError(f"unknown search provider {name!r}; choose from {sorted(REGISTRY)}")
        out.append(cls(cfg))
    return out
