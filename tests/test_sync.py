import unittest

import _bootstrap  # noqa: F401

from open_audio_fetch import sync


class TestParseMix(unittest.TestCase):
    def test_default_shape(self):
        self.assertEqual(sync.parse_mix("audiobooks=40,music=40,podcasts=20"),
                         {"audiobooks": 40, "music": 40, "podcasts": 20})

    def test_bad_term(self):
        with self.assertRaises(ValueError):
            sync.parse_mix("music=lots")

    def test_unknown_category(self):
        with self.assertRaises(ValueError):
            sync.parse_mix("jazz=100")

    def test_zero_mix(self):
        with self.assertRaises(ValueError):
            sync.parse_mix("music=0")


class TestUsableAndNormalize(unittest.TestCase):
    def test_drops_category_missing_keys(self):
        mix = {"audiobooks": 40, "music": 40, "podcasts": 20}
        # podcasts needs PODCASTINDEX_KEY/_SECRET; none in this env.
        usable = sync.usable_categories(
            mix,
            registry=["librivox", "internetarchive", "podcastindex"],
            env={},  # no keys
        )
        self.assertEqual(set(usable), {"audiobooks", "music"})

    def test_keeps_podcasts_when_keyed(self):
        mix = {"podcasts": 20}
        usable = sync.usable_categories(
            mix, registry=["podcastindex"],
            env={"PODCASTINDEX_KEY": "k", "PODCASTINDEX_SECRET": "s"},
        )
        self.assertEqual(usable, ["podcasts"])

    def test_normalize_reallocates(self):
        mix = {"audiobooks": 40, "music": 40, "podcasts": 20}
        frac = sync.normalize_mix(mix, ["audiobooks", "music"])
        self.assertAlmostEqual(frac["audiobooks"], 0.5)
        self.assertAlmostEqual(frac["music"], 0.5)
        self.assertNotIn("podcasts", frac)
        self.assertAlmostEqual(sum(frac.values()), 1.0)


class TestBudget(unittest.TestCase):
    def test_plan_budget_reserve_and_cap(self):
        self.assertEqual(sync.plan_budget(1000, 200), 800)
        self.assertEqual(sync.plan_budget(1000, 200, max_bytes=500), 500)
        self.assertEqual(sync.plan_budget(100, 500), 0)  # reserve exceeds free

    def test_category_budgets_split(self):
        b = sync.category_budgets(1000, {"audiobooks": 0.5, "music": 0.5})
        self.assertEqual(b, {"audiobooks": 500, "music": 500})


if __name__ == "__main__":
    unittest.main()
