"""PR2: source reliability, evidence strength and evidence balance stay separate."""
import json
import unittest

from dai.claims.normalize import extract_features
from dai.core.models import Claim
from dai.i18n.tokenize import content_stems
from dai.render.text_out import render_text
from dai.synthesis.strength import evidence_strength

from dai.core.pipeline import run_research
from helpers import FakeFetcher, test_config
from test_pipeline import Q, URLS, make_db


def mk(text, ctype="fact", rel=1.0):
    nums, ctx, dates = extract_features(text, "en")
    return Claim(text=text, normalized=text.lower(), lang="en", claim_type=ctype,
                 numbers=nums, num_ctx=ctx, dates=dates,
                 stems=content_stems(text, "en"), relevance=rel)


class StrengthUnit(unittest.TestCase):
    def test_direct_fact_beats_opinion_and_forecast(self):
        rep = mk("The tower is 320 metres tall.")
        fact = evidence_strength(rep, rep)[0]
        opinion = evidence_strength(mk("The tower is 320 metres tall.", "opinion"), rep)[0]
        forecast = evidence_strength(mk("The tower is 320 metres tall.", "forecast"), rep)[0]
        self.assertGreater(fact, forecast)
        self.assertGreater(forecast, opinion)

    def test_every_claim_type_has_a_factor(self):
        from dai.claims.segment import classify_type
        from dai.synthesis.strength import TYPE_FACTOR
        samples = ["The tower is tall.", "The tower is 320 metres tall.",
                   "I think the tower is ugly.", "The tower will be 400 metres tall next year.",
                   'The mayor said "the tower is the tallest building in the whole region".']
        for t in samples:
            nums, _, _ = extract_features(t, "en")
            self.assertIn(classify_type(t, "en", nums), TYPE_FACTOR, t)

    def test_statistic_is_as_strong_as_fact(self):
        rep = mk("The tower is 320 metres tall.", "statistic")
        self.assertEqual(evidence_strength(rep, rep)[0], 1.0)

    def test_low_relevance_weakens_evidence(self):
        rep = mk("The tower is 320 metres tall.")
        self.assertGreater(evidence_strength(mk(rep.text, rel=1.0), rep)[0],
                           evidence_strength(mk(rep.text, rel=0.2), rep)[0])

    def test_signals_are_explained(self):
        rep = mk("The tower is 320 metres tall.")
        _, sig = evidence_strength(rep, rep)
        self.assertEqual(len(sig), 3)
        self.assertTrue(all(isinstance(x, str) for x in sig))


class JsonKeepsThreeConcepts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run_research(Q, urls=list(URLS), cfg=test_config(), db=make_db(),
                               fetcher=FakeFetcher(URLS), record=False)
        cls.d = json.loads(cls.res.json())

    def test_evidence_has_reliability_and_strength_separately(self):
        ev = [e for s in self.d["statements"] for e in s["supporting"] + s["dissent"]]
        self.assertTrue(ev)
        for e in ev:
            self.assertIn("source_reliability", e)
            self.assertIn("evidence_strength", e)
            self.assertNotIn("trust", e)
            self.assertTrue(0 <= e["evidence_strength"] <= 1)

    def test_statement_has_balance_not_confidence(self):
        for s in self.d["statements"]:
            self.assertIn("evidence_balance", s)
            self.assertNotIn("confidence", s)

    def test_references_carry_reliability_only(self):
        for r in self.d["references"]:
            self.assertIn("source_reliability", r)
            self.assertNotIn("evidence_strength", r)   # strength belongs to a quote, not a source

    def test_text_names_all_three_measures(self):
        txt = self.res.text()
        self.assertIn("evidence balance", txt)
        self.assertIn("source reliability", txt)

    def test_v1_audit_records_still_render(self):
        old = {"query": "q", "stats": {}, "errors": [], "output_language": "tr",
               "references": [{"ref": 1, "url": "https://x.example", "title": "", "trust": 0.7}],
               "statements": [{"statement": "S", "confidence": 0.4, "status": "single-source",
                               "supporting": [{"ref": 1, "quote": "S"}], "dissent": [], "notes": []}]}
        out = render_text(old)
        self.assertIn("kanıt dengesi 40%", out)
        self.assertIn("kaynak güvenilirliği 70", out)


if __name__ == "__main__":
    unittest.main()
