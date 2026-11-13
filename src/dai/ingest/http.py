"""Minimal, safe HTTP GET on top of urllib (stdlib only)."""
from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin

from ..core.errors import FetchError
from .safety import check_url


@dataclass
class Response:
    url: str
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    truncated: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, cfg):
        self.cfg = cfg
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > self.cfg.max_redirects:
            raise FetchError("too many redirects")
        newurl = urljoin(req.full_url, newurl)
        check_url(newurl, self.cfg.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _inflate(body: bytes, enc: str, limit: int) -> tuple[bytes, bool]:
    enc = (enc or "").lower()
    if enc not in ("gzip", "x-gzip", "deflate"):
        return body, False
    try:
        if enc == "deflate":
            try:
                d = zlib.decompressobj(zlib.MAX_WBITS)
                out = d.decompress(body, limit + 1)
            except zlib.error:
                d = zlib.decompressobj(-zlib.MAX_WBITS)
                out = d.decompress(body, limit + 1)
        else:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            out = d.decompress(body, limit + 1)
    except zlib.error as e:
        raise FetchError(f"bad compressed body: {e}") from e
    if len(out) > limit:
        return out[:limit], True
    return out, False


def http_get(url: str, cfg, headers: dict | None = None) -> Response:
    check_url(url, cfg.allow_private)
    h = {"User-Agent": cfg.user_agent,
         "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8,*/*;q=0.1",
         "Accept-Language": "en,tr;q=0.8",
         "Accept-Encoding": "gzip, deflate"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    opener = urllib.request.build_opener(_SafeRedirect(cfg))
    try:
        resp = opener.open(req, timeout=cfg.timeout)
    except urllib.error.HTTPError as e:
        resp = e
    except FetchError:
        raise
    except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError,
            ConnectionError, OSError, ValueError) as e:
        raise FetchError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from e
    try:
        limit = cfg.max_bytes
        chunks, total, truncated = [], 0, False
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
            if total > limit:
                truncated = True
                break
        body = b"".join(chunks)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        body, t2 = _inflate(body, hdrs.get("content-encoding", ""), limit)
        if len(body) > limit:
            body, truncated = body[:limit], True
        return Response(url=resp.geturl(), status=getattr(resp, "status", None) or resp.code,
                        headers=hdrs, body=body, truncated=truncated or t2)
    except (socket.timeout, TimeoutError, OSError) as e:
        raise FetchError(f"read failed: {e}") from e
    finally:
        resp.close()
