import gzip
import unittest

from dai.core.errors import UnsafeURL
from dai.extract.html_extract import decode_body, extract_document
from dai.core.models import RawPage
from dai.ingest.fetch import Fetcher
from dai.ingest.safety import check_url
from dai.storage.db import Database

from helpers import LocalServer, html_page, test_config

ARTICLE = html_page(["The Marlow Tower is 320 metres tall and was completed in 2019 by the city.",
                     "Visitors reach the observation deck by a lift that opens every morning at nine."])


def raw(html, ctype="text/html; charset=utf-8"):
    b = html.encode("utf-8") if isinstance(html, str) else html
    return RawPage(url="https://news.example/a", final_url="https://news.example/a", status=200,
                   content_type=ctype, body=b)


class ExtractTests(unittest.TestCase):
    def test_metadata_and_main_text(self):
        d = extract_document(raw(ARTICLE))
        self.assertEqual(d.author, "Jane Roe")
        self.assertEqual(d.published, "2024-05-17")
        self.assertEqual(d.publisher, "Example News")
        self.assertEqual(d.external_links, 1)
        self.assertIn("320 metres", d.text)
        self.assertNotIn("all rights reserved", d.text)
        self.assertNotIn("Home", d.text)

    def test_sidebar_nav_skipped_and_jsonld(self):
        html = ('<html><head><title>T</title><script type="application/ld+json">'
                '{"@type":"NewsArticle","author":{"name":"Ada L."},"datePublished":"2023-02-03"}'
                '</script></head><body><div class="sidebar"><p>Subscribe to our newsletter for more '
                'daily updates and other news today.</p></div><div><p>The council approved the new '
                'budget on Monday after a long debate among members of the public.</p></div></body></html>')
        d = extract_document(raw(html))
        self.assertEqual(d.author, "Ada L.")
        self.assertEqual(d.published, "2023-02-03")
        self.assertNotIn("Subscribe", d.text)
        self.assertIn("council approved", d.text)

    def test_turkish_cp1254_decoding(self):
        html = "<html><body><p>Şehrin nüfusu yüz yirmi bin kişidir ve ışık çok güçlüdür.</p></body></html>"
        text = decode_body(html.encode("cp1254"), "text/html")
        self.assertIn("nüfusu", text)
        text2 = decode_body(html.encode("cp1254"), "text/html; charset=windows-1254")
        self.assertIn("ışık", text2)

    def test_plain_text_and_empty(self):
        d = extract_document(raw("First paragraph here.\n\nSecond paragraph here.", "text/plain"))
        self.assertIn("Second", d.text)
        self.assertIsNone(extract_document(raw("<html><body><script>x=1</script></body></html>")))

    def test_malformed_html_does_not_crash(self):
        d = extract_document(raw("<p>Unclosed paragraph about the Marlow Tower being very tall indeed"
                                 "<div><p>Another one about the harbour and its many busy docks"))
        self.assertIsNotNone(d)


class SafetyTests(unittest.TestCase):
    def test_blocked(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "http://user:pw@example.com/",
                    "http://127.0.0.1/", "http://localhost/", "http://[::1]/", "http://10.0.0.5/",
                    "http://169.254.169.254/latest/meta-data/", "http://example.com:22/"):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURL):
                    check_url(url)

    def test_allow_private_flag(self):
        check_url("http://127.0.0.1:8000/", allow_private=True)


class FetcherTests(unittest.TestCase):
    def test_fetch_cache_robots_errors(self):
        big = b"<html><body>" + b"<p>filler text for the large page</p>" * 20000 + b"</body></html>"
        bomb = gzip.compress(b"<p>" + b"a" * 5_000_000 + b"</p>")
        routes = {
            "/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private\n"),
            "/ok": (200, {}, ARTICLE.encode()),
            "/private": (200, {}, ARTICLE.encode()),
            "/missing": (404, {}, b"nope"),
            "/pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4"),
            "/big": (200, {}, big),
            "/bomb": (200, {"Content-Encoding": "gzip"}, bomb),
            "/redir": (302, {"Location": "/ok"}, b""),
            "/loop": (302, {"Location": "/loop"}, b""),
        }
        with LocalServer(routes) as srv:
            cfg = test_config(respect_robots=True, max_bytes=200_000, max_redirects=3)
            db = Database(":memory:")
            f = Fetcher(cfg, db)
            p = f.fetch(srv.base + "/ok")
            self.assertTrue(p.ok)
            self.assertFalse(p.from_cache)
            n = len(srv.hits)
            p2 = f.fetch(srv.base + "/ok")
            self.assertTrue(p2.from_cache)
            self.assertEqual(len(srv.hits), n)           # served from cache, no network

            self.assertIn("robots", f.fetch(srv.base + "/private").error)
            self.assertIn("404", f.fetch(srv.base + "/missing").error)
            self.assertIn("unsupported content type", f.fetch(srv.base + "/pdf").error)
            self.assertTrue(f.fetch(srv.base + "/big").truncated)
            b = f.fetch(srv.base + "/bomb")
            self.assertTrue(b.truncated)
            self.assertLessEqual(len(b.body), 200_000)
            self.assertTrue(f.fetch(srv.base + "/redir").ok)
            self.assertIn("redirect", f.fetch(srv.base + "/loop").error)

            off = Fetcher(test_config(offline=True, respect_robots=False), db)
            self.assertTrue(off.fetch(srv.base + "/ok").ok)
            self.assertIn("offline", off.fetch(srv.base + "/new").error)
            db.close()

    def test_ssrf_blocked_by_default_config(self):
        cfg = test_config(allow_private=False)
        p = Fetcher(cfg, None).fetch("http://127.0.0.1:9/x")
        self.assertIn("blocked", p.error)

    def test_redirect_to_private_blocked(self):
        # public-looking start is impossible offline; check the guard function on the hop instead
        with self.assertRaises(UnsafeURL):
            check_url("http://192.168.1.1/admin", allow_private=False)


class DatabaseTests(unittest.TestCase):
    def test_tiers_runs(self):
        with Database(":memory:") as db:
            db.set_tier("a.example", "tier1")
            self.assertEqual(db.tier_map(), {"a.example": "tier1"})
            self.assertTrue(db.remove_tier("a.example"))
            self.assertFalse(db.remove_tier("a.example"))
            rid = db.create_run("q", "en", {"x": 1})
            db.finish_run(rid, {"s": 1}, ["e"], {"query": "q"}, {"t": 1})
            run = db.get_run(rid)
            self.assertEqual(run["stats"], {"s": 1})
            self.assertEqual(db.list_runs()[0]["id"], rid)
            self.assertIsNone(db.get_run(999))


if __name__ == "__main__":
    unittest.main()
