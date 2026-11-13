import unittest

from dai.claims.normalize import dates_incompatible, extract_dates, extract_features
from dai.claims.segment import classify_type, extract_claims, make_claim, split_sentences
from dai.i18n.tokenize import (content_tokens, detect_language, fold, is_negated, stem,
                               tokens)
from dai.ingest.urls import canonical_url, registered_domain, url_key


class TokenizeTests(unittest.TestCase):
    def test_turkish_letters_survive(self):
        self.assertEqual(content_tokens("Türkiye'nin nüfusu için önemli", "tr"),
                         ["türkiye", "nüfusu", "önemli"])

    def test_dotted_dotless_i_fold(self):
        self.assertEqual(fold("İstanbul"), fold("ISTANBUL"))
        self.assertEqual(fold("ISPARTA"), fold("ısparta"))

    def test_english_nt_dropped(self):
        self.assertNotIn("isn", tokens("It isn't true"))

    def test_stem_consistency(self):
        self.assertEqual(stem("metres", "en"), stem("metre", "en"))
        self.assertEqual(stem("completed", "en"), stem("complete", "en"))

    def test_language_detection(self):
        self.assertEqual(detect_language("Kentin nüfusu kaç?"), "tr")
        self.assertEqual(detect_language("How tall is the Marlow Tower?"), "en")

    def test_negation(self):
        self.assertTrue(is_negated("It isn't approved", "en"))
        self.assertTrue(is_negated("The ministry did not approve it", "en"))
        self.assertFalse(is_negated("Not only is it tall but wide", "en"))
        self.assertTrue(is_negated("Bakanlık raporu onaylamadı.", "tr"))
        self.assertFalse(is_negated("Bakanlık raporu onayladı.", "tr"))
        self.assertFalse(is_negated("Yeni bir komedi filmi çıktı.", "tr"))


class NormalizeTests(unittest.TestCase):
    def nums(self, text, lang="en"):
        return extract_features(text, lang)[0]

    def test_number_formats(self):
        self.assertEqual(self.nums("a total of 1,234.5 units"), (1234.5,))
        self.assertEqual(self.nums("toplam 1.234,5 birim", "tr"), (1234.5,))
        self.assertEqual(self.nums("pi is 3.14 roughly"), (3.14,))
        self.assertEqual(self.nums("nüfus 10.000 kişi", "tr"), (10000.0,))

    def test_multipliers_percent_units(self):
        self.assertEqual(self.nums("cost 5 million dollars"), (5e6,))
        self.assertEqual(self.nums("nüfus 120 bin kişi", "tr"), (120000.0,))
        self.assertEqual(self.nums("rose 12% last year"), (12.0,))
        self.assertEqual(self.nums("yüzde 12 arttı", "tr"), (12.0,))
        self.assertEqual(self.nums("5 km"), self.nums("5000 m"))

    def test_ordinals_and_glued_ids_ignored(self):
        self.assertEqual(self.nums("the 3rd floor of COVID-19 ward"), ())

    def test_dates(self):
        d, _ = extract_dates(fold("on 17 May 2024 and May 5, 2023"))
        self.assertEqual(d, ("2023-05-05", "2024-05-17"))
        d, _ = extract_dates(fold("17 Mayıs 2024 tarihinde"), "tr")
        self.assertEqual(d, ("2024-05-17",))
        d, _ = extract_dates("in 2019", "en")
        self.assertEqual(d, ("2019",))

    def test_year_with_unit_is_not_a_date(self):
        d, _ = extract_dates("it is 2000 metres high")
        self.assertEqual(d, ())

    def test_dates_incompatible(self):
        self.assertFalse(dates_incompatible(("2024",), ("2024-05-17",)))
        self.assertTrue(dates_incompatible(("2023",), ("2024",)))
        self.assertFalse(dates_incompatible((), ("2024",)))


class SegmentTests(unittest.TestCase):
    def test_abbreviations_and_decimals(self):
        s = [x[0] for x in split_sentences(
            "Dr. Smith measured 3.5 metres. The U.S. record, e.g. in March, stands. Done now.")]
        self.assertEqual(len(s), 3)
        self.assertTrue(s[0].startswith("Dr. Smith"))

    def test_claim_types(self):
        self.assertEqual(classify_type("The tower is 320 metres tall.", "en", (320.0,)), "statistic")
        self.assertEqual(classify_type("The city will build a new bridge next year.", "en", ()), "forecast")
        self.assertEqual(classify_type("I think this is the best tower ever built.", "en", ()), "opinion")
        self.assertEqual(classify_type('The mayor said "we are very proud of this achievement".',
                                       "en", ()), "quote")
        self.assertEqual(classify_type("The council approved the plan.", "en", ()), "fact")

    def test_boilerplate_and_questions_filtered(self):
        text = ("Subscribe to our newsletter for daily updates and more news.\n\n"
                "Is the tower really that tall in the end?\n\n"
                "The Marlow Tower was completed in the year 2019 by the city.")
        cl = extract_claims(text, "u", "en")
        self.assertEqual(len(cl), 1)
        self.assertIn("Marlow", cl[0].text)

    def test_subject_predicate(self):
        c = make_claim("The Marlow Tower is 320 metres tall.", "en")
        self.assertEqual(c.predicate, "be")
        self.assertIn("marlow", c.subject)
        self.assertIn("marlow", c.entities)


class UrlTests(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(canonical_url("HTTP://Example.com:80/a/?utm_source=x&b=2&a=1#f"),
                         "http://example.com/a?a=1&b=2")
        self.assertEqual(url_key("https://www.x.com/p/"), url_key("http://x.com/p"))

    def test_registered_domain(self):
        self.assertEqual(registered_domain("www.tuik.gov.tr"), "tuik.gov.tr")
        self.assertEqual(registered_domain("news.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(registered_domain("127.0.0.1"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
