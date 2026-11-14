"""Per-key (domain) politeness delay, safe across threads."""
from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, delay: float):
        self.delay = delay
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str, delay: float | None = None) -> None:
        d = self.delay if delay is None else max(self.delay, delay)
        if d <= 0:
            return
        with self._lock:
            now = time.monotonic()
            t = max(now, self._next.get(key, 0.0))
            self._next[key] = t + d
        if t > now:
            time.sleep(t - now)
