"""Pr3 regression tests: every case comes from a failure seen in real runs (Windows, 14 Nov).

The page texts are written for these tests in the same shape as the real pages; no network.
"""
import json
import time
import unittest

from dai.agents.planner import agent_research
from dai.analysis.cluster import cluster_similarity
from dai.analysis.relations import classify_pair
from dai.claims.normalize import extract_features
from dai.claims.question import profile_question, rank_results, search_queries
from dai.claims.segment import extract_claims, make_claim
from dai.config import Config
from dai.core.models import RawPage
from dai.core.pipeline import ResearchSession, run_research
from dai.discovery.base import SearchResult
from dai.i18n.tokenize import is_negated
from dai.ingest.fetch import Fetcher
from dai.storage.db import Database

from helpers import FILLER_EN, FakeFetcher, FakeProvider, html_page, test_config

SPECIAL = "KATHMANDU: The highest point on Earth rose a little on Tuesday after China and Nepal agreed on one precise elevation for Mount Everest."


def page(title, paras, **kw):
    return html_page(paras, title=title, **kw)


EVEREST_PAGES = {
    "https://news.example/dawn": page(
        "Earth's highest point gets higher as China, Nepal revise Everest height",
        [SPECIAL,
         "The agreed height of 8,848.86 metres (29,031 feet) was announced at a news conference in "
         "Kathmandu, and it is 86 centimetres higher than the figure Nepal used before."] + FILLER_EN,
        site="Dawn-like"),
    "https://ref.example/guide": page(
        "Highest mountain",
        ["It was named Mount Everest after Colonel Sir George Everest, who never saw the mountain "
         "himself during his years as Surveyor-General of India.",
         "Mount Everest is 8,849 metres tall according to the figure on the climbing permit."]
        + FILLER_EN, site="Guide", author="Ann Lee"),
}
Q = "How tall is Mount Everest?"


def research(q, pages, **cfg):
    return run_research(q, urls=list(pages), cfg=test_config(**cfg), db=Database(":memory:"),
                        fetcher=FakeFetcher(pages), record=False)


class QuantityQuestions(unittest.TestCase):
    def test_answer_sentence_beats_mentions(self):
        res = research(Q, EVEREST_PAGES)
        texts = [s.text for s in res.statements]
        self.assertTrue(texts, "no statements")
        self.assertTrue(any("8,848.86" in t for t in texts), texts)
        self.assertFalse(any("named Mount Everest after" in t for t in texts), texts)
        self.assertFalse(any(t.startswith("KATHMANDU") for t in texts), texts)

    def test_title_supplies_the_subject(self):
        """'The agreed height of 8,848.86 metres' never repeats 'Everest'; the page title does."""
        res = research(Q, {"https://news.example/dawn": EVEREST_PAGES["https://news.example/dawn"]})
        self.assertTrue(any("8,848.86" in s.text for s in res.statements))

    def test_other_name_next_to_the_number_is_demoted(self):
        pages = {"https://a.example/a": page("Everest and K2", [
            "There was no doubt that Everest remains the highest peak because Mount K2 is only "
            "8,611 metres tall.",
            "The summit of Mount Everest stands 8,849 metres tall above sea level."] + FILLER_EN)}
        res = research(Q, pages)
        self.assertIn("8,849", res.statements[0].text)

    def test_year_in_question_prefers_that_year(self):
        pages = {"https://a.example/a": page("Survey history", [
            "British surveyors first measured Mount Everest at 8,840 metres tall in 1856.",
            "A later survey put Mount Everest at 8,848 metres tall in 1955."] + FILLER_EN)}
        res = research("How tall was Mount Everest in 1856?", pages)
        self.assertIn("1856", res.statements[0].text)

    def test_deep_answer_survives_the_per_document_cap(self):
        words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike".split()
        filler = [f"The {a} team describes the weather and the trail conditions near the {b} base camp "
                  f"during the long expedition season." for a in words for b in words][:150]
        deep = ["Mount Everest is 8,849 metres tall by the most widely quoted survey figure."]
        pages = {"https://a.example/a": page("Expedition diary", filler + deep)}
        res = research(Q, pages, max_claims_per_doc=10)
        self.assertTrue(any("8,849" in s.text for s in res.statements))

    def test_turkish_quantity_question(self):
        pages = {"https://a.example/a": page("Türkiye demografisi", [
            "Türkiye'nin nüfusu 85.372.377 kişidir ve nüfusun büyük bölümü kentlerde yaşar.",
            "Türkiye'nin başkenti Ankara'dır ve ülkenin en kalabalık şehri İstanbul'dur.",
            "Bu maddede Türkiye sınırları içinde yaşayan nüfusa ve bu nüfusun çeşitli "
            "özelliklerine ait veriler bulunur."] + [
            "Ülkenin birçok bölgesinde yaz ayları sıcak geçer ve kış ayları oldukça soğuk olur."],
            lang="tr")}
        res = research("Türkiye'nin nüfusu kaç?", pages)
        self.assertIn("85.372.377", res.statements[0].text)
        self.assertFalse(any("Bu maddede" in s.text for s in res.statements))


class QuestionProfileTests(unittest.TestCase):
    def test_profiles(self):
        p = profile_question("How tall is Mount Everest?", "en")
        self.assertEqual((p.kind, p.unit, p.entities), ("quantity", "len", ("Mount Everest",)))
        p = profile_question("What is the population of Norway?", "en")
        self.assertEqual((p.kind, p.unit), ("quantity", "count"))
        p = profile_question("How tall was Mount Everest in 1856?", "en")
        self.assertEqual(p.years, ("1856",))
        p = profile_question("Türkiye'nin nüfusu kaç?", "tr")
        self.assertEqual((p.kind, p.unit, p.entities), ("quantity", "count", ("Türkiye",)))
        p = profile_question("İstanbul hangi yıl fethedildi?", "tr")
        self.assertEqual(p.kind, "date")
        p = profile_question("Is Pluto a planet?", "en")
        self.assertEqual(p.kind, "open")
        self.assertEqual(p.entities, ("Pluto",))

    def test_search_queries_are_short(self):
        self.assertEqual(search_queries("What is the population of Norway?", "en"),
                         ["population Norway", "Norway"])

    def test_results_ranked_by_title(self):
        res = [SearchResult(url="u1", title="Norwegian Minnesotans"),
               SearchResult(url="u2", title="Demographics of Norway"),
               SearchResult(url="u3", title="Norway")]
        order = [r.title for r in rank_results(res, "What is the population of Norway?", "en")]
        self.assertEqual(order[0], "Norway")
        self.assertEqual(order[-1], "Norwegian Minnesotans")


class NumbersAndDates(unittest.TestCase):
    def test_second_quantity_is_not_multiplied_by_first_units(self):
        nums, _, _ = extract_features("It is 39.5 AU (5.91 billion km; 3.67 billion mi) away.", "en")
        self.assertIn(5.91e12, nums)
        self.assertFalse(any(n > 1e15 for n in nums), nums)

    def test_feet_are_lengths(self):
        nums, ctx, _ = extract_features("The tower is 324 metres (1,063 ft) tall.", "en")
        self.assertAlmostEqual(nums[1], 324.0, delta=0.1)
        self.assertIn("@len", ctx[1])

    def test_old_years_are_dates_only_with_a_cue(self):
        self.assertEqual(extract_features("Constantinople fell in 1453 after a siege.", "en")[2], ("1453",))
        self.assertEqual(extract_features("İstanbul 1453 yılında fethedildi.", "tr")[2], ("1453",))
        nums, _, dates = extract_features("The village has 1500 people and 1750 houses.", "en")
        self.assertEqual(dates, ())
        self.assertIn(1500.0, nums)

    def test_footnote_markers_are_not_numbers_or_text(self):
        cs = extract_claims("The tower is 330 metres tall.[9] It opened to the public in 1889.[17][a] "
                            "A guard was posted nearby.[citation needed]", "u", "en")
        for c in cs:
            self.assertNotIn("[", c.text)
        self.assertNotIn(9.0, cs[0].numbers)

    def test_hatnotes_captions_and_navigation_are_not_claims(self):
        text = ("From Wikipedia, the free encyclopedia\n\nThis article is about the dwarf planet. "
                "For the deity, see Pluto (mythology).\n\nSun · Saturn · Uranus · Neptune · Pluto\n\n"
                "FILE - In this May 27, 2020, file photo, a team heads for the summit of the mountain.\n\n"
                "Pluto was discovered in 1930 by Clyde W. Tombaugh at the Lowell Observatory.\n\n"
                "Please help update this article to reflect recent events or newly available information.")
        out = [c.text for c in extract_claims(text, "u", "en")]
        self.assertEqual(len(out), 1, out)
        self.assertIn("Tombaugh", out[0])

    def test_abbreviation_does_not_split_the_sentence(self):
        from dai.claims.segment import split_sentences
        s = split_sentences("A team reached the summit of Mount Everest, known locally as Mt. Qomolangma, on Tuesday. Next.")
        self.assertEqual(len(s), 2)


class RelationRules(unittest.TestCase):
    def _c(self, t):
        return make_claim(t, "en", "d")

    def test_close_numbers_are_agreement_with_a_visible_note(self):
        a = self._c("British surveyors first measured the height of Everest in 1856 at 8,840 meters.")
        b = self._c("The height of Everest was first determined by British surveyors in 1856 at 8,842 meters.")
        r = classify_pair(a, b, Config())
        self.assertEqual(r.kind, "agreement")
        self.assertTrue(any(s.startswith("approximate numeric match") for s in r.signals), r.signals)

    def test_close_numbers_surface_as_note(self):
        pages = {"https://a.example/a": page("Survey", [
            "British surveyors first measured the height of Mount Everest in 1856 at 8,840 meters."] + FILLER_EN),
            "https://b.example/b": page("Another report", [
                "The height of Mount Everest was first determined by British surveyors in 1856 at "
                "8,842 meters."] + FILLER_EN, author="Bo", site="B")}
        res = research("How tall was Mount Everest in 1856?", pages)
        top = res.statements[0]
        self.assertTrue(any(n[0] == "approx" for n in top.notes), top.notes)

    def test_one_shared_name_is_not_a_contradiction(self):
        a = self._c("According to Kapoor, the design brief asked for a tower of at least 100 metres in Eiffel style.")
        b = self._c("The Gliwice Radio Tower is 112 metres tall with a wooden framework of larch.")
        self.assertNotEqual(classify_pair(a, b, Config()).kind, "contradiction")

    def test_unrelated_facts_are_not_clustered_by_one_name(self):
        a = self._c("According to Kapoor, the design brief from the Mayor's office was for a tower of at "
                    "least 100 metres, while Balmond wanted an icon to match the Eiffel Tower.")
        b = self._c("Its central feature is a 108-metre-tall replica of the Eiffel Tower, with French-style "
                    "radiating avenues and baroque fountains.")
        self.assertLess(cluster_similarity(a, b, 0.5), 0.5)

    def test_negation_idioms(self):
        self.assertFalse(is_negated("Many objects were measured as larger than Pluto, igniting a debate "
                                    "over whether or not to consider them planets.", "en"))
        self.assertFalse(is_negated("There was no doubt that Everest would remain the highest peak.", "en"))
        self.assertTrue(is_negated("Planet X, as Lowell defined it, does not exist.", "en"))


class Independence(unittest.TestCase):
    def test_copies_count_once_and_say_so(self):
        text = ["KATHMANDU, Nepal (AP) — China and Nepal announced a new official height for Mount "
                "Everest on Tuesday, ending a discrepancy between the two nations.",
                "The new official height of Mount Everest is 8,848.86 metres tall, officials said."] + FILLER_EN
        pages = {f"https://{n}.example/story": page("Height of Mt. Everest taller than reported", text,
                                                     site=n.upper(), author="")
                 for n in ("kutv", "weartv", "newschannel")}
        res = research(Q, pages)
        self.assertEqual(res.stats["independent_groups"], 1)
        top = res.statements[0]
        self.assertEqual(top.status, "single-source")
        self.assertTrue(any(n[0] == "copies" and n[1] == "3" and n[2] == "1" for n in top.notes), top.notes)
        self.assertIn("count as 1 independent", res.text())


class PlumbingFixes(unittest.TestCase):
    def test_blocked_urls_are_not_blamed_on_robots(self):
        f = Fetcher(Config(respect_robots=True, allow_private=False, rate_delay=0.0, retries=0))
        for url, want in (("http://127.0.0.1:9/x", "blocked:"), ("ftp://example.com/x", "blocked: scheme")):
            page_ = f.fetch(url)
            self.assertFalse(page_.ok)
            self.assertTrue(page_.error.startswith(want), page_.error)
            self.assertNotIn("robots", page_.error)

    def test_cached_row_with_null_body_is_a_miss(self):
        db = Database(":memory:")
        db._exec("INSERT INTO pages (key,url,final_url,status,content_type,fetched_at,content_hash,"
                 "truncated,body) VALUES ('k','u','u',200,'text/html',?,'h',0,NULL)", (time.time(),), commit=True)
        self.assertIsNone(db.get_page("k"))
        self.assertEqual(db.cache_stats()["pages"], 0)       # the damaged row was dropped

    def test_concurrent_cache_use_does_not_break(self):
        from concurrent.futures import ThreadPoolExecutor
        db = Database(":memory:")
        for i in range(30):
            db.put_page(f"k{i}", RawPage(url=f"u{i}", final_url=f"u{i}", status=200,
                                         content_type="text/html", body=b"<p>x</p>" * 50,
                                         fetched_at=time.time(), content_hash="h"))

        def work(i):
            db.put_page(f"n{i}", RawPage(url="u", final_url="u", status=200, content_type="text/html",
                                         body=b"y" * 100, fetched_at=time.time(), content_hash="h"))
            return db.get_page(f"k{i % 30}")
        with ThreadPoolExecutor(8) as ex:
            got = list(ex.map(work, range(200)))
        self.assertTrue(all(g is not None and g.body for g in got))

    def test_soft_404_page_is_skipped_with_a_warning(self):
        pages = {"https://a.example/gone": page("404 - Page Not Found",
                                                ["Sorry, the page you were looking for could not be located on "
                                                 "this server any more, please try the search box instead."] + FILLER_EN)}
        res = research(Q, pages)
        self.assertEqual(res.stats["documents"], 0)
        self.assertTrue(any("soft 404" in e for e in res.errors), res.errors)

    def test_language_mismatch_is_explained(self):
        pages = {"https://a.example/a": page("Mount Everest", [
            "Mount Everest is 8,849 metres tall and sits on the border of Nepal and China."] + FILLER_EN)}
        res = research("Everest'in yüksekliği kaç metre?", pages, default_language="tr")
        self.assertEqual(res.statements, [])
        self.assertTrue(any("question language" in e for e in res.errors), res.errors)

    def test_agent_first_round_leaves_budget_for_follow_ups(self):
        urls = {f"https://s{i}.example/p": page(f"Page {i}", FILLER_EN, site=f"s{i}") for i in range(12)}
        provider = FakeProvider({}, default=list(urls))
        res = agent_research(Q, cfg=test_config(max_sources=4, agent_rounds=1), db=Database(":memory:"),
                             fetcher=FakeFetcher(urls), providers=[provider], record=False)
        self.assertEqual(res.stats["documents"], 4)
        self.assertTrue(any("independent source group" in e for e in res.errors) or
                        res.stats["independent_groups"] >= 3)

    def test_strength_reflects_answer_shape(self):
        res = research(Q, EVEREST_PAGES)
        top = res.statements[0]
        self.assertTrue(any("asks for a len value" in s for e in top.supporting for s in e.strength_signals))
        json.dumps(res.to_dict())


if __name__ == "__main__":
    unittest.main()
