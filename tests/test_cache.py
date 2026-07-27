import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import _bootstrap  # noqa: F401

from open_audio_fetch.cache import AvailabilityCache
from open_audio_fetch.sites import MediaItem


class TestAvailabilityCache(unittest.TestCase):
    def _cache(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Point the repo-shard fallback at an empty dir so tests are hermetic.
        return AvailabilityCache(
            "fake", base_dir=Path(tmp.name), fallback_dir=Path(tmp.name) / "none"
        )

    def test_round_trip_reconstructs_items(self):
        c = self._cache()
        items = [
            MediaItem(url="http://h/a", title="A", author="X", album="Alb",
                      source="fake", ext="flac", license="public-domain"),
            MediaItem(url="http://h/b", title="B", author="Y", source="fake"),
        ]
        c.save(items, now=1000.0)
        loaded = c.load()
        self.assertEqual(len(loaded), 2)
        self.assertEqual({i.url for i in loaded}, {"http://h/a", "http://h/b"})
        a = next(i for i in loaded if i.url == "http://h/a")
        self.assertEqual((a.ext, a.album, a.license), ("flac", "Alb", "public-domain"))

    def test_missing_cache_loads_none(self):
        self.assertIsNone(self._cache().load())

    def test_freshness_by_ttl(self):
        c = self._cache()
        c.save([], now=1000.0)
        self.assertTrue(c.fresh(ttl_seconds=100, now=1050.0))   # 50s old
        self.assertFalse(c.fresh(ttl_seconds=100, now=1200.0))  # 200s old

    def test_deterministic_sorted_output(self):
        c = self._cache()
        items = [MediaItem(url=f"http://h/{i}", title=str(i), source="fake")
                 for i in (3, 1, 2)]
        c.save(items, now=1.0)
        text = c.path.read_text()
        # URLs appear in sorted order regardless of input order.
        self.assertLess(text.index("http://h/1"), text.index("http://h/2"))
        self.assertLess(text.index("http://h/2"), text.index("http://h/3"))


if __name__ == "__main__":
    unittest.main()
