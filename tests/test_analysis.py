import unittest

from dai.analysis.cluster import analyze, cluster_claims
from dai.analysis.independence import group_documents, wire_tags
from dai.analysis.relations import classify_pair
from dai.claims.segment import make_claim
from dai.core.models import Document
from dai.synthesis.confidence import confidence, status
from dai.trust.score import score_source
from dai.trust.tiers import lookup_tier

from helpers import test_config

CFG = test_config()

PAIRS = [
    ("The Marlow Tower is 320 metres tall and was completed in 2019.",
     "According to the city planning office, the Marlow Tower stands 320 metres tall.",
     "en", "agreement"),
    ("The Marlow Tower is 320 metres tall and was completed in 2019.",
     "The Marlow Tower is 305 metres tall, local media wrote.", "en", "contradiction"),
    ("The ministry approved the new Atlas Bridge project after a long review.",
     "The ministry did not approve the new Atlas Bridge project after a long review.",
     "en", "contradiction"),
    ("Unemployment was 5.2% in March 2024.", "Unemployment was 5.6% in April 2024.",
     "en", "update"),
    ("The tower was completed in 2019.", "The tower was completed in 2020.", "en", "contradiction"),
    ("The route is 5 km long according to the report.", "The route is 5000 m long according to the report.",
     "en", "agreement"),
    ("Kentin nüfusu 120 bin kişidir.", "Kentin nüfusu 150 bin kişidir.", "tr", "contradiction"),
    ("Bakanlık raporu onayladı.", "Bakanlık raporu onaylamadı.", "tr", "contradiction"),
    ("The harbour handles 4 million tonnes of cargo.", "Weather in the region stays mild all spring.",
     "en", "unrelated"),
]


class RelationTests(unittest.TestCase):
    def test_table(self):
        for a, b, lang, want in PAIRS:
            with self.subTest(a=a, b=b):
                r = classify_pair(make_claim(a, lang), make_claim(b, lang), CFG)
                self.assertEqual(r.kind, want, r.signals)
                self.assertTrue(r.signals)          # explainable

    def test_negation_beats_high_overlap(self):
        a = ("The regional council of the northern district formally approved the long awaited "
             "Atlas Bridge construction project on Monday")
        b = a.replace("formally approved", "formally did not approve")
        r = classify_pair(make_claim(a + ".", "en"), make_claim(b + ".", "en"), CFG)
        self.assertEqual(r.kind, "contradiction")

    def test_more_detailed_claim_is_not_a_conflict(self):
        a = make_claim("The Marlow Tower is 320 metres tall.", "en")
        b = make_claim("The Marlow Tower is 320 metres tall and has 70 floors.", "en")
        self.assertNotEqual(classify_pair(a, b, CFG).kind, "contradiction")

    def test_unrelated_numbers_do_not_conflict(self):
        a = make_claim("The Marlow Tower is 320 metres tall.", "en")
        b = make_claim("The Marlow Tower is home to 12000 workers.", "en")
        self.assertNotEqual(classify_pair(a, b, CFG).kind, "contradiction")


class ClusterTests(unittest.TestCase):
    def claims(self):
        texts = ["The Marlow Tower is 320 metres tall.",
                 "According to officials the Marlow Tower stands 320 metres tall.",
                 "The Marlow Tower is 305 metres tall, local media wrote.",
                 "The harbour handles 4 million tonnes of cargo each year."]
        return [make_claim(t, "en") for t in texts]

    def test_clusters_and_determinism(self):
        c = self.claims()
        a1 = [cl.members for cl in cluster_claims(c, CFG)]
        a2 = [cl.members for cl in cluster_claims(list(c), CFG)]
        self.assertEqual(a1, a2)
        self.assertEqual(a1[0], [0, 1, 2])
        self.assertEqual(a1[1], [3])

    def test_relations_collected(self):
        cl = analyze(self.claims(), CFG)[0]
        kinds = {(r.a, r.b): r.kind for r in cl.relations}
        self.assertEqual(kinds[(0, 1)], "agreement")
        self.assertEqual(kinds[(0, 2)], "contradiction")

    def test_empty_subject_does_not_merge_unrelated(self):
        a = make_claim("5 million tonnes of grain were shipped.", "en")
        b = make_claim("12 weeks of drought hit the farms nearby.", "en")
        self.assertEqual(len(cluster_claims([a, b], CFG)), 2)


def doc(url, domain, text, **kw):
    return Document(url=url, domain=domain, text=text, word_count=len(text.split()), **kw)


class IndependenceTests(unittest.TestCase):
    TEXT = ("The Marlow Tower is 320 metres tall and was completed in 2019 according to the "
            "official planning documents published by the city office this spring season.")

    def test_copy_same_domain_and_wire(self):
        d = [doc("https://a.example/1", "a.example", self.TEXT),
             doc("https://b.example/2", "b.example", self.TEXT),                      # copy
             doc("https://a.example/3", "a.example", "Completely different words here about harbours."),
             doc("https://c.example/4", "c.example", "(Reuters) - Rain fell across the northern valley today."),
             doc("https://d.example/5", "d.example", "Floods hit the south, according to Reuters on Friday."),
             doc("https://e.example/6", "e.example", "An unrelated sentence about mountain railways and tunnels.")]
        g = group_documents(d)
        self.assertEqual(g[d[0].url], g[d[1].url])
        self.assertEqual(g[d[0].url], g[d[2].url])
        self.assertEqual(g[d[3].url], g[d[4].url])
        self.assertNotEqual(g[d[0].url], g[d[5].url])
        self.assertNotEqual(g[d[3].url], g[d[5].url])

    def test_wire_tags(self):
        self.assertIn("reuters", wire_tags(doc("https://reuters.com/x", "reuters.com", "text")))
        self.assertIn("aa", wire_tags(doc("u", "x.tr", "Haber (AA) — Başkan bugün açıklama yaptı.")))


class TrustTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(lookup_tier("www.reuters.com")[0], "tier1")
        self.assertEqual(lookup_tier("stats.gov.tr")[0], "tier1")
        self.assertEqual(lookup_tier("old.reddit.com")[0], "tier3")
        self.assertEqual(lookup_tier("random-site.example")[0], "unrated")
        self.assertEqual(lookup_tier("reuters.com", {"reuters.com": "tier3"})[0], "tier3")

    def test_scores_ordered_and_explained(self):
        good = doc("https://www.reuters.com/a", "reuters.com", "word " * 600, author="A. Writer",
                   published="2024-01-01", external_links=4, title="Council approves budget")
        bad = doc("http://x.blogspot.com/a", "blogspot.com", "wow! " * 30, title="SHOCKING!! YOU WON'T BELIEVE THIS")
        g, b = score_source(good.url, good), score_source(bad.url, bad)
        self.assertGreater(g.score, 0.85)
        self.assertLess(b.score, 0.4)
        self.assertTrue(b.signals)
        self.assertTrue(0 <= b.score <= 1 and 0 <= g.score <= 1)


class ConfidenceTests(unittest.TestCase):
    def test_monotonic_and_bounded(self):
        p, d = 0.5, 0.75
        one = confidence([0.9], [], p, d)
        two = confidence([0.9, 0.9], [], p, d)
        many = confidence([0.9] * 20, [], p, d)
        self.assertLess(one, two)
        self.assertLess(two, many)
        self.assertLess(many, 1.0)
        self.assertLess(confidence([0.9], [0.9], p, d), one)

    def test_status(self):
        self.assertEqual(status(1, [0.9], [], 0.75), "single-source")
        self.assertEqual(status(2, [0.9, 0.9], [], 0.75), "corroborated")
        self.assertEqual(status(1, [0.9], [0.9], 0.75), "disputed")
        self.assertEqual(status(2, [0.9, 0.9], [0.3], 0.75), "mixed")


if __name__ == "__main__":
    unittest.main()
