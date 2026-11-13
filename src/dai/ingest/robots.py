"""robots.txt handling (RFC 9309 semantics, conservative on server errors)."""
from __future__ import annotations

import threading
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ..core.errors import FetchError
from .http import http_get


class RobotsCache:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = cfg.user_agent.split("/")[0].split()[0] or "D-AI"
        self._cache: dict[str, tuple[RobotFileParser | None, bool]] = {}
        self._lock = threading.Lock()

    def _load(self, base: str):
        try:
            r = http_get(base + "/robots.txt", self.cfg)
        except FetchError:
            return None, False          # unreachable -> disallow
        if r.status == 200:
            rp = RobotFileParser()
            rp.parse(r.body.decode("utf-8", errors="replace").splitlines())
            return rp, True
        if 400 <= r.status < 500:
            return None, True           # no robots.txt -> allow all
        return None, False              # 5xx -> disallow

    def _entry(self, url: str):
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            if base not in self._cache:
                self._cache[base] = self._load(base)
            return self._cache[base]

    def allowed(self, url: str) -> bool:
        rp, ok = self._entry(url)
        if rp is None:
            return ok
        return rp.can_fetch(self.token, url)

    def crawl_delay(self, url: str) -> float:
        rp, _ = self._entry(url)
        if rp is None:
            return 0.0
        d = rp.crawl_delay(self.token)
        return min(float(d), 10.0) if d else 0.0
