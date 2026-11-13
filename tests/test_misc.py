import os
import tempfile
import unittest
from unittest import mock

from dai.config import load_config
from dai.core.errors import ConfigError
from dai.discovery import providers as prov
from dai.discovery.providers import SearxngProvider, WikipediaProvider, build_providers

from helpers import LocalServer, test_config


class ProviderTests(unittest.TestCase):
    def test_wikipedia_parsing_and_language_host(self):
        seen = {}

        def fake(url, cfg, headers=None):
            seen["url"] = url
            return {"query": {"search": [{"title": "Marlow Tower", "snippet": "tall"},
                                         {"title": "Türkiye (ülke)", "snippet": ""}]}}

        with mock.patch.object(prov, "_get_json", fake):
            res = WikipediaProvider(test_config()).search("marlow tower", 5, "tr")
        self.assertTrue(seen["url"].startswith("https://tr.wikipedia.org/w/api.php?"))
        self.assertEqual(res[0].url, "https://tr.wikipedia.org/wiki/Marlow_Tower")
        self.assertIn("%C3%BC", res[1].url)

    def test_searxng_against_local_server(self):
        body = b'{"results":[{"url":"https://a.example/x","title":"A","content":"s"},{"title":"no url"}]}'
        with LocalServer({"/search": (200, {"Content-Type": "application/json"}, body)}) as srv:
            p = SearxngProvider(test_config(searxng_url=srv.base))
            res = p.search("q", 5, "en")
        self.assertEqual([r.url for r in res], ["https://a.example/x"])

    def test_provider_config_errors(self):
        with self.assertRaises(ConfigError):
            build_providers(test_config(providers=("nope",)))
        with self.assertRaises(ConfigError):
            build_providers(test_config(providers=("searxng",)))
        with self.assertRaises(ConfigError):
            build_providers(test_config(providers=("brave",)))

    def test_provider_failure_is_a_warning(self):
        from dai.core.pipeline import run_research
        from dai.storage.db import Database

        class Boom:
            name = "boom"

            def search(self, *a, **k):
                raise RuntimeError("down")

        res = run_research("How tall is the Marlow Tower?", cfg=test_config(),
                           db=Database(":memory:"), providers=[Boom()], record=False)
        self.assertTrue(any("boom" in e and "down" in e for e in res.errors))


class ConfigTests(unittest.TestCase):
    def test_file_env_override_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write('max_sources = 3\nproviders = ["wikipedia", "searxng"]\noutput_language = "tr"\n')
            os.environ["DAI_HOME"] = d
            try:
                cfg = load_config(path=path)
                self.assertEqual((cfg.max_sources, cfg.providers, cfg.output_language),
                                 (3, ("wikipedia", "searxng"), "tr"))
                os.environ["DAI_MAX_SOURCES"] = "5"
                self.assertEqual(load_config(path=path).max_sources, 5)
                self.assertEqual(load_config(overrides={"max_sources": 9}, path=path).max_sources, 9)
                self.assertIsNone(load_config(overrides={"max_sources": None}, path=path).brave_key or None)
            finally:
                os.environ.pop("DAI_MAX_SOURCES", None)
                os.environ.pop("DAI_HOME", None)

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write("bogus = 1\n")
            with self.assertRaises(ConfigError):
                load_config(path=path)
            with self.assertRaises(ConfigError):
                load_config(overrides={"bogus": 1}, path=os.path.join(d, "none.toml"))

    def test_secret_redacted_in_snapshot(self):
        self.assertEqual(test_config(brave_key="secret").snapshot()["brave_key"], "***")


if __name__ == "__main__":
    unittest.main()
