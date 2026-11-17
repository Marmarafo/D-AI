"""URL helpers: canonicalisation, registered-domain extraction."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(
    r"^(utm_|fbclid$|gclid$|dclid$|mc_cid$|mc_eid$|igshid$|yclid$|_ga$|ref_src$|spm$|cmpid$)", re.I)
_SECOND_LEVEL = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.tr", "org.tr", "net.tr", "gov.tr", "edu.tr", "k12.tr", "av.tr", "bel.tr", "gen.tr",
    "web.tr", "tsk.tr", "pol.tr", "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp", "com.br", "gov.br", "co.in", "gov.in",
    "co.nz", "co.za", "com.cn", "com.mx", "com.ar", "com.sg", "com.hk", "com.tw",
}


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def registered_domain(host: str) -> str:
    host = host.lower().strip(".")
    if not host or is_ip(host):
        return host
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last2 = ".".join(labels[-2:])
    if last2 in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return last2


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    port = p.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    q.sort()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, urlencode(q), ""))


def url_key(url: str) -> str:
    """Dedupe key: http/https and www. are treated as the same page."""
    c = canonical_url(url)
    p = urlsplit(c)
    host = p.netloc
    if host.startswith("www."):
        host = host[4:]
    return host + p.path + (("?" + p.query) if p.query else "")
