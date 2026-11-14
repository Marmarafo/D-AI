"""URL safety: scheme allow-list, credential ban, SSRF guard."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from ..core.errors import UnsafeURL

_ALLOWED_PORTS = {None, 80, 443, 8080, 8443}


def check_url(url: str, allow_private: bool = False) -> None:
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError as e:
        raise UnsafeURL(f"malformed URL: {e}") from e
    if p.scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme not allowed: {p.scheme or '(none)'}")
    host = p.hostname
    if not host:
        raise UnsafeURL("URL has no host")
    if p.username or p.password:
        raise UnsafeURL("credentials in URL are not allowed")
    if allow_private:
        return
    if port not in _ALLOWED_PORTS:
        raise UnsafeURL(f"port not allowed: {port}")
    try:
        infos = socket.getaddrinfo(host, port or (443 if p.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except OSError as e:
        raise UnsafeURL(f"cannot resolve host {host!r}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeURL(f"host {host!r} resolves to a non-public address ({ip})")
