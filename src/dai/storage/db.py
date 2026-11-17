"""SQLite storage: page cache, source tiers, run audit trail."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from ..core.models import RawPage
from ..paths import is_shared_storage

SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    key TEXT PRIMARY KEY, url TEXT, final_url TEXT, status INTEGER, content_type TEXT,
    fetched_at REAL, content_hash TEXT, truncated INTEGER, body BLOB);
CREATE TABLE IF NOT EXISTS tiers (domain TEXT PRIMARY KEY, tier TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, lang TEXT, started REAL, finished REAL,
    config_json TEXT, stats_json TEXT, errors_json TEXT, result_json TEXT, trace_json TEXT);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self.warning = None
        if path != ":memory:" and is_shared_storage(path):
            self.warning = ("database is on Android shared storage; SQLite locking is "
                            "unreliable there. Use a path under $HOME instead.")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _exec(self, sql, args=(), commit=False):
        """Run a statement under the lock. Rows are fetched inside the lock too (see _rows):
        a cursor read after the lock is released can race with another thread's statement on
        the shared connection (the fetcher runs several threads)."""
        with self._lock:
            cur = self._conn.execute(sql, args)
            if commit:
                self._conn.commit()
            return cur

    def _rows(self, sql, args=()) -> list:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # ---- page cache
    def get_page(self, key: str) -> RawPage | None:
        rows = self._rows("SELECT * FROM pages WHERE key=?", (key,))
        if not rows:
            return None
        r = rows[0]
        if r["body"] is None:            # damaged row: treat as a cache miss and drop it
            self._exec("DELETE FROM pages WHERE key=?", (key,), commit=True)
            return None
        return RawPage(url=r["url"], final_url=r["final_url"], status=r["status"],
                       content_type=r["content_type"], body=bytes(r["body"]),
                       fetched_at=r["fetched_at"], content_hash=r["content_hash"],
                       from_cache=True, truncated=bool(r["truncated"]))

    def put_page(self, key: str, p: RawPage):
        self._exec("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?)",
                   (key, p.url, p.final_url, p.status, p.content_type, p.fetched_at,
                    p.content_hash, int(p.truncated), p.body), commit=True)

    def cache_stats(self) -> dict:
        r = self._rows("SELECT COUNT(*) n, COALESCE(SUM(LENGTH(body)),0) b FROM pages")[0]
        return {"pages": r["n"], "bytes": r["b"]}

    def clear_cache(self, older_than: float | None = None) -> int:
        if older_than is None:
            cur = self._exec("DELETE FROM pages", commit=True)
        else:
            cur = self._exec("DELETE FROM pages WHERE fetched_at < ?",
                             (time.time() - older_than,), commit=True)
        return cur.rowcount

    # ---- tiers
    def list_tiers(self) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT domain, tier FROM tiers ORDER BY domain")]

    def tier_map(self) -> dict:
        return {r["domain"]: r["tier"] for r in self._rows("SELECT domain, tier FROM tiers")}

    def set_tier(self, domain: str, tier: str):
        self._exec("INSERT OR REPLACE INTO tiers VALUES (?,?)", (domain, tier), commit=True)

    def remove_tier(self, domain: str) -> bool:
        return self._exec("DELETE FROM tiers WHERE domain=?", (domain,), commit=True).rowcount > 0

    # ---- runs
    def create_run(self, question: str, lang: str, config: dict) -> int:
        cur = self._exec("INSERT INTO runs (question, lang, started, config_json) VALUES (?,?,?,?)",
                         (question, lang, time.time(), json.dumps(config, ensure_ascii=False)),
                         commit=True)
        return cur.lastrowid

    def finish_run(self, run_id: int, stats: dict, errors: list, result: dict, trace: dict):
        dump = lambda o: json.dumps(o, ensure_ascii=False)
        self._exec("UPDATE runs SET finished=?, stats_json=?, errors_json=?, result_json=?, "
                   "trace_json=? WHERE id=?",
                   (time.time(), dump(stats), dump(errors), dump(result), dump(trace), run_id),
                   commit=True)

    def get_run(self, run_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM runs WHERE id=?", (run_id,))
        if not rows:
            return None
        d = dict(rows[0])
        for k in ("config_json", "stats_json", "errors_json", "result_json", "trace_json"):
            d[k[:-5]] = json.loads(d.pop(k)) if d.get(k) else None
        return d

    def list_runs(self, limit: int = 20) -> list[dict]:
        rows = self._rows("SELECT id, question, started, finished FROM runs "
                          "ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
