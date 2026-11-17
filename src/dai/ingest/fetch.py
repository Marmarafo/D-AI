"""Page fetcher: cache, robots.txt, rate limit, retries, content-type checks."""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from ..core.errors import FetchError, UnsafeURL
from ..core.models import RawPage
from .http import http_get
from .ratelimit import RateLimiter
from .robots import RobotsCache
from .safety import check_url
from .urls import host_of, url_key

_OK_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class Fetcher:
    def __init__(self, cfg, db=None):
        self.cfg = cfg
        self.db = db
        self.limiter = RateLimiter(cfg.rate_delay)
        self.robots = RobotsCache(cfg) if cfg.respect_robots else None

    def _err(self, url: str, msg: str, status: int = 0) -> RawPage:
        return RawPage(url=url, final_url=url, status=status, error=msg, fetched_at=time.time())

    def fetch(self, url: str) -> RawPage:
        try:
            check_url(url, self.cfg.allow_private)      # scheme / SSRF checks come before robots
        except UnsafeURL as e:
            return self._err(url, f"blocked: {e}")
        key = url_key(url)
        cached = self.db.get_page(key) if self.db else None
        if cached is not None:
            fresh = (time.time() - cached.fetched_at) < self.cfg.cache_ttl
            if fresh or self.cfg.offline:
                return cached
        if self.cfg.offline:
            return self._err(url, "offline mode: page not in cache")
        try:
            page = self._fetch_network(url)
        except UnsafeURL as e:
            return self._err(url, f"blocked: {e}")
        except FetchError as e:
            if cached is not None:           # stale copy beats nothing
                return cached
            return self._err(url, str(e))
        if page.ok and self.db:
            self.db.put_page(key, page)
        return page

    def _fetch_network(self, url: str) -> RawPage:
        host = host_of(url)
        if self.robots is not None:
            if not self.robots.allowed(url):
                raise FetchError("disallowed by robots.txt")
            delay = self.robots.crawl_delay(url)
        else:
            delay = 0.0
        last: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            self.limiter.wait(host, delay)
            try:
                r = http_get(url, self.cfg)
            except UnsafeURL:
                raise
            except FetchError as e:
                last = e
                time.sleep(min(2.0, 0.5 * (attempt + 1)))
                continue
            if r.status in (429, 500, 502, 503, 504) and attempt < self.cfg.retries:
                last = FetchError(f"HTTP {r.status}")
                time.sleep(min(2.0, 0.5 * (attempt + 1)))
                continue
            return self._to_page(url, r)
        raise FetchError(str(last) if last else "fetch failed")

    def _to_page(self, url: str, r) -> RawPage:
        ctype = r.content_type.split(";")[0].strip().lower()
        base = dict(url=url, final_url=r.url, status=r.status, content_type=r.content_type,
                    fetched_at=time.time(), truncated=r.truncated)
        if not 200 <= r.status < 300:
            return RawPage(**base, error=f"HTTP {r.status}")
        if ctype and ctype not in _OK_TYPES:
            return RawPage(**base, error=f"unsupported content type: {ctype}")
        if not ctype and not r.body.lstrip()[:1] == b"<":
            return RawPage(**base, error="unknown content type")
        return RawPage(**base, body=r.body, content_hash=hashlib.sha256(r.body).hexdigest())

    def fetch_many(self, urls: list[str]) -> list[RawPage]:
        if not urls:
            return []
        with ThreadPoolExecutor(max_workers=max(1, self.cfg.max_workers)) as ex:
            return list(ex.map(self.fetch, urls))
