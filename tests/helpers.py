import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dai.config import Config
from dai.core.models import RawPage
from dai.discovery.base import SearchResult


def test_config(**kw) -> Config:
    base = dict(rate_delay=0.0, retries=0, respect_robots=False, allow_private=True,
                providers=(), max_workers=2, timeout=5.0)
    base.update(kw)
    return Config(**base)


def html_page(paragraphs, title="Report", author="Jane Roe", date="2024-05-17",
              site="Example News", links=("https://source.example/report",), lang="en"):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    ext = "".join(f'<a href="{u}">source</a> ' for u in links)
    return (f'<html lang="{lang}"><head><title>{title}</title>'
            f'<meta name="author" content="{author}">'
            f'<meta property="article:published_time" content="{date}T08:00:00Z">'
            f'<meta property="og:site_name" content="{site}"></head><body>'
            f'<nav><a href="/">Home</a></nav><article><h1>{title}</h1>{body}<p>{ext}</p></article>'
            f'<footer>(c) all rights reserved</footer></body></html>')


FILLER_EN = ["Visitors reach the observation deck by a high-speed lift that opens every morning "
             "at nine and closes in the early evening hours.",
             "The surrounding district has been redeveloped over the last decade with new parks, "
             "cycle lanes and a modern transport interchange."]
FILLER_B = ["Local shops along the river front stay open late on weekends and the market square "
            "hosts a small craft fair during the warmer months of the year.",
            "A new ferry timetable was published last week and the operator says that crossings "
            "will become more frequent from the start of next month."]
FILLER_G = ["The regional museum announced extended opening hours for students and families "
            "together with a series of free evening lectures on local history.",
            "Road works near the central bridge are expected to continue through the autumn "
            "although pedestrians can still cross using the temporary walkway."]
FILLER_TR = ["Şehir merkezindeki yeni park bu yıl ziyaretçilere açıldı ve çocuklar için geniş "
             "oyun alanları ile yürüyüş yolları içeriyor.",
             "Belediye başkanlığı önümüzdeki aylarda ulaşım ağında yeni düzenlemeler yapılacağını "
             "duyurdu ve çalışmalar planlandığı şekilde sürüyor."]
FILLER_TR2 = ["Kıyıdaki balıkçı barınağı yenilendi ve sabah erken saatlerde taze deniz ürünleri "
              "satan küçük bir pazar kuruldu.",
              "Üniversite kampüsünde düzenlenen kitap fuarı hafta sonu boyunca açık kalacak ve "
              "yazarlarla söyleşiler yapılacak."]


class FakeFetcher:
    """Serves HTML from a dict; None value means the page fails."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        body = self.pages.get(url)
        if body is None:
            return RawPage(url=url, final_url=url, status=404, error="HTTP 404",
                           fetched_at=time.time())
        b = body.encode("utf-8") if isinstance(body, str) else body
        return RawPage(url=url, final_url=url, status=200, content_type="text/html; charset=utf-8",
                       body=b, fetched_at=time.time(), content_hash=str(hash(b)))

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


class FakeProvider:
    name = "fake"

    def __init__(self, mapping, default=()):
        self.mapping = mapping
        self.default = list(default)
        self.queries = []

    def search(self, query, limit, lang="en"):
        self.queries.append(query)
        return [SearchResult(url=u) for u in self.mapping.get(query, self.default)][:limit]


class LocalServer:
    """routes: path -> (status, headers, body bytes) or callable(handler)->tuple"""

    def __init__(self, routes):
        self.routes = routes
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                r = outer.routes.get(self.path.split("?")[0])
                if r is None:
                    r = (404, {}, b"not found")
                status, headers, body = r(self) if callable(r) else r
                self.send_response(status)
                headers = dict(headers)
                headers.setdefault("Content-Type", "text/html; charset=utf-8")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.hits = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
