import contextlib
import io
import json
import os
import tempfile
import unittest

from dai.agents.planner import agent_research
from dai.cli.main import main
from dai.core.models import Evidence
from dai.core.pipeline import ResearchSession, run_research
from dai.render.refs import RefRegistry
from dai.render.text_out import render_text
from dai.storage.db import Database

from helpers import (FILLER_B, FILLER_EN, FILLER_G, FILLER_TR, FILLER_TR2, FakeFetcher, FakeProvider, LocalServer, html_page,
                     test_config)

ALPHA = ["The Marlow Tower is 320 metres tall and was completed in 2019. It is the tallest building in the city."] + FILLER_EN
BETA = ["According to the city planning office, the Marlow Tower stands 320 metres tall. Construction finished in 2019."] + FILLER_B
GAMMA = ["The Marlow Tower is 305 metres tall, local media wrote. Several residents disagree about the figure."] + FILLER_G
DELTA = list(ALPHA)  # syndicated copy of alpha

URLS = {
    "https://alpha.example/a": html_page(ALPHA, site="Alpha"),
    "https://beta.example/b": html_page(BETA, author="Bo Li", site="Beta"),
    "https://gamma.example/c": html_page(GAMMA, author="", site="", links=()),
    "https://delta.example/d": html_page(DELTA, author="Dee", site="Delta"),
    "https://dead.example/x": None,
}
Q = "How tall is the Marlow Tower?"


def make_db():
    db = Database(":memory:")
    db.set_tier("alpha.example", "tier1")
    return db


class EnglishEndToEnd(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db.close)
        self.res = run_research(Q, urls=list(URLS), cfg=test_config(), db=self.db,
                                fetcher=FakeFetcher(URLS))

    def test_consensus_with_independence_and_dissent(self):
        top = self.res.statements[0]
        self.assertIn("320", top.text)
        self.assertEqual(top.independent_sources, 2)            # alpha+delta collapse, beta
        self.assertEqual(top.status, "mixed")
        self.assertEqual({e.url for e in top.dissent}, {"https://gamma.example/c"})
        urls = {e.url for e in top.supporting}
        self.assertTrue({"https://alpha.example/a", "https://beta.example/b"} <= urls)

    def test_minority_claim_is_flagged_not_hidden(self):
        minority = [s for s in self.res.statements if "305" in s.text][0]
        self.assertIn(minority.status, ("disputed", "mixed"))
        self.assertLess(minority.confidence, self.res.statements[0].confidence)
        self.assertEqual(minority.independent_sources, 1)

    def test_stats_errors_and_irrelevant_claims_dropped(self):
        st = self.res.stats
        self.assertEqual(st["documents"], 4)
        self.assertEqual(st["independent_groups"], 3)
        self.assertEqual(st["sources_failed"], 1)
        self.assertTrue(any("dead.example" in e for e in self.res.errors))
        self.assertFalse(any("observation deck" in s.text for s in self.res.statements))

    def test_json_and_text_shape(self):
        d = json.loads(self.res.json())
        self.assertEqual(d["schema"], "dai.result/2")
        refs = {r["ref"]: r for r in d["references"]}
        for s in d["statements"]:
            for e in s["supporting"] + s["dissent"]:
                self.assertIn(e["ref"], refs)
                self.assertEqual(refs[e["ref"]]["url"], e["url"])
        txt = self.res.text()
        self.assertIn("Q: How tall", txt)
        self.assertIn("References:", txt)
        self.assertIn("disputed by", txt)
        self.assertIn("not a probability", txt)

    def test_deterministic(self):
        again = run_research(Q, urls=list(URLS), cfg=test_config(), db=make_db(),
                             fetcher=FakeFetcher(URLS), record=False)
        a = json.loads(self.res.json())
        b = json.loads(again.json())
        a["stats"].pop("timing", None)
        self.assertEqual(a["statements"], b["statements"])

    def test_audit_trail_stored_and_rerenderable(self):
        run = self.db.get_run(self.res.run_id)
        self.assertEqual(run["question"], Q)
        self.assertTrue(run["trace"]["clusters"])
        kinds = {r["kind"] for c in run["trace"]["clusters"] for r in c["relations"]}
        self.assertTrue({"agreement", "contradiction"} <= kinds)
        self.assertIn("Marlow", render_text(run["result"]))


class OtherPipelineTests(unittest.TestCase):
    def test_turkish_end_to_end(self):
        pages = {
            "https://bir.example/1": html_page(["Kentin nüfusu 120 bin kişidir ve her yıl artmaktadır."] + FILLER_TR, lang="tr"),
            "https://iki.example/2": html_page(["Resmi kayıtlara göre kentin nüfusu 150 bin kişidir."] + FILLER_TR2, lang="tr"),
        }
        res = run_research("Kentin nüfusu kaç?", urls=list(pages), cfg=test_config(),
                           db=Database(":memory:"), fetcher=FakeFetcher(pages), record=False)
        self.assertEqual(res.language, "tr")
        self.assertEqual(len(res.statements), 2)
        self.assertTrue(all(s.dissent for s in res.statements))
        txt = res.text()
        self.assertIn("Soru: Kentin", txt)
        self.assertIn("karşı görüş", txt)

    def test_update_is_not_dissent(self):
        pages = {
            "https://a.example/1": html_page(["The unemployment rate was 5.2% in March 2024 across the whole region."] + FILLER_EN),
            "https://b.example/2": html_page(["The unemployment rate was 5.6% in April 2024 across the whole region."] + FILLER_B),
        }
        res = run_research("What is the unemployment rate?", urls=list(pages), cfg=test_config(),
                           db=Database(":memory:"), fetcher=FakeFetcher(pages), record=False)
        self.assertEqual(len(res.statements), 2)
        for s in res.statements:
            self.assertEqual(s.dissent, ())
            self.assertTrue(any(n[0] == "update" for n in s.notes))

    def test_no_sources_and_all_failed(self):
        res = run_research(Q, cfg=test_config(), db=Database(":memory:"), providers=[],
                           fetcher=FakeFetcher({}), record=False)
        self.assertEqual(res.statements, [])
        self.assertTrue(any("no sources found" in e for e in res.errors))
        self.assertIn("No supported statements", res.text())
        res = run_research(Q, urls=["https://x.example/1"], cfg=test_config(),
                           db=Database(":memory:"), fetcher=FakeFetcher({}), record=False)
        self.assertEqual(res.stats["sources_failed"], 1)

    def test_source_budget_respected(self):
        s = ResearchSession(Q, test_config(max_sources=2), Database(":memory:"),
                            FakeFetcher(URLS), providers=[])
        s.ingest([u for u in URLS if URLS[u]])
        self.assertEqual(len(s.docs), 2)

    def test_opinions_excluded(self):
        pages = {"https://a.example/1": html_page(
            ["I think the Marlow Tower is the best tall tower ever built in this region."] + FILLER_EN)}
        res = run_research(Q, urls=list(pages), cfg=test_config(), db=Database(":memory:"),
                           fetcher=FakeFetcher(pages), record=False)
        self.assertEqual(res.statements, [])
        self.assertGreaterEqual(res.stats["claims_skipped_type"], 1)


class AgentTests(unittest.TestCase):
    def test_agent_follows_up_when_thin(self):
        provider = FakeProvider({
            "tall Marlow Tower": ["https://alpha.example/a"],      # discovery now sends short queries
            "tall marlow tower": ["https://beta.example/b", "https://gamma.example/c"],
        })
        res = agent_research(Q, cfg=test_config(agent_rounds=3, agent_min_independent=3),
                             db=make_db(), fetcher=FakeFetcher(URLS), providers=[provider],
                             record=False)
        self.assertGreaterEqual(len(provider.queries), 2)
        self.assertEqual(res.stats["documents"], 3)
        steps = res.trace["agent"]["steps"]
        self.assertEqual(steps[0]["tool"], "search")
        self.assertIn("stop_reason", res.trace["agent"])
        json.dumps(res.trace)                                    # trace must be serialisable

    def test_agent_stops_when_goals_met(self):
        provider = FakeProvider({"tall Marlow Tower": ["https://alpha.example/a",
                                                       "https://beta.example/b",
                                                       "https://delta.example/d"]})
        pages = {k: v for k, v in URLS.items() if "gamma" not in k}
        pages["https://eps.example/e"] = html_page(
            ["Officials confirm that the Marlow Tower is 320 metres tall."] + FILLER_G)
        provider.mapping["tall Marlow Tower"].append("https://eps.example/e")
        res = agent_research(Q, cfg=test_config(agent_rounds=3, agent_min_independent=3),
                             db=make_db(), fetcher=FakeFetcher(pages), providers=[provider],
                             record=False)
        self.assertEqual(res.trace["agent"]["stop_reason"], "goals met")
        self.assertEqual(provider.queries, ["tall Marlow Tower", "Marlow Tower"])   # one search round

    def test_agent_accepts_urls_with_flag(self):
        res = agent_research(Q, urls=["https://alpha.example/a"], cfg=test_config(agent_rounds=1),
                             db=make_db(), fetcher=FakeFetcher(URLS), providers=[], record=False)
        self.assertEqual(res.stats["documents"], 1)


class RenderTests(unittest.TestCase):
    def test_refs_dedupe_canonical(self):
        r = RefRegistry()
        a = r.add("https://www.x.com/p/?utm_source=a", "T")
        b = r.add("http://x.com/p", "T")
        self.assertEqual(a, b)
        self.assertEqual(len(r.refs), 1)

    def test_text_render_none_safe(self):
        d = {"query": "q", "stats": {}, "errors": [], "references": [
            {"ref": 1, "url": "https://x.example", "title": "", "trust": None}],
            "statements": [{"statement": "S", "confidence": 0.5, "status": "weird",
                            "supporting": [{"ref": 1, "quote": ""}],
                            "dissent": [{"ref": 1, "quote": "x" * 300}], "notes": []}]}
        out = render_text(d, "en")
        self.assertIn("...", out)
        self.assertIn("[1] https://x.example", out)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for k, v in {"DAI_HOME": self.tmp.name, "DAI_RATE_DELAY": "0", "DAI_RETRIES": "0",
                     "DAI_PROVIDERS": ""}.items():
            os.environ[k] = v
            self.addCleanup(os.environ.pop, k, None)

    def test_sources_roundtrip_and_validation(self):
        self.assertEqual(self.run_cli("sources", "add", "https://WWW.Example.com/x", "tier1")[0], 0)
        rc, out, _ = self.run_cli("sources", "list")
        self.assertIn("tier1  example.com", out)
        self.assertEqual(self.run_cli("sources", "add", "a.com", "tier9")[0], 2)
        self.assertEqual(self.run_cli("sources", "add", "a.com")[0], 2)
        self.assertIn("removed", self.run_cli("sources", "remove", "example.com")[1])

    def test_config_and_bad_key(self):
        rc, out, _ = self.run_cli("config")
        self.assertEqual(rc, 0)
        self.assertIn('"max_sources"', out)
        os.environ["DAI_MAX_SOURCES"] = "abc"
        self.addCleanup(os.environ.pop, "DAI_MAX_SOURCES", None)
        rc, _, err = self.run_cli("config")
        self.assertEqual(rc, 1)
        self.assertIn("invalid value", err)

    def test_research_live_local_server_audit_and_offline(self):
        routes = {"/a": (200, {}, html_page(ALPHA).encode()), "/b": (200, {}, html_page(GAMMA).encode())}
        with LocalServer(routes) as srv:
            args = ["research", Q, "--url", srv.base + "/a", "--url", srv.base + "/b",
                    "--allow-private", "--json"]
            rc, out, err = self.run_cli(*args)
            self.assertEqual(rc, 0, err)
            d = json.loads(out)
            self.assertEqual(d["schema"], "dai.result/2")
            self.assertTrue(d["statements"])
            n = len(srv.hits)
        # server is gone: offline run must succeed from cache
        rc, out, err = self.run_cli("research", Q, "--url", srv.base + "/a", "--offline",
                                    "--allow-private")
        self.assertEqual(rc, 0, err)
        self.assertIn("320", out)
        rc, out, _ = self.run_cli("audit", "1", "--format", "text")
        self.assertEqual(rc, 0)
        self.assertIn("Marlow", out)
        self.assertEqual(self.run_cli("audit", "99")[0], 1)
        rc, out, _ = self.run_cli("cache", "stats")
        self.assertIn("pages: 2", out)

    def test_exit_code_when_nothing_found(self):
        rc, out, err = self.run_cli("research", Q, "--url", "http://127.0.0.1:9/none",
                                    "--allow-private")
        self.assertEqual(rc, 3)
        self.assertIn("No supported statements", out)


if __name__ == "__main__":
    unittest.main()
