import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import _bootstrap  # noqa: F401

from open_audio_fetch.fetcher import Fetcher, dedupe_key, discover, parse_size, sanitize
from open_audio_fetch.sites import MediaItem, SiteAdapter


class FakeClient:
    """A network-free stand-in for PoliteClient."""

    def __init__(self, pages):
        self.pages = pages
        self.downloaded = []
        self.header_calls = []

    def get_text(self, url, headers=None):
        self.header_calls.append((url, headers))
        return self.pages[url]

    def download(self, url, dest, headers=None):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = b"FAKEAUDIO" * 3
        dest.write_bytes(data)
        self.downloaded.append(url)
        return len(data)


class OnePageAdapter(SiteAdapter):
    name = "fake"

    def __init__(self, items, headers=None):
        self._items = items
        self._headers = headers or {}

    def seeds(self):
        return ["page1"]

    def next_links(self, url, body):
        return []

    def extract_media(self, url, body):
        return list(self._items)

    def headers_for(self, url):
        return self._headers


class TestSanitize(unittest.TestCase):
    def test_removes_unsafe_and_trims(self):
        self.assertEqual(sanitize('a/b:c*?"<>|d'), "a b c d")
        self.assertEqual(sanitize("   ...  "), "untitled")
        self.assertEqual(sanitize("x" * 300, maxlen=10), "xxxxxxxxxx")


class TestEngineFiling(unittest.TestCase):
    def _run(self, items, **kw):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        client = FakeClient({"page1": "body"})
        adapter = OnePageAdapter(items, headers=kw.pop("headers", None))
        fetcher = Fetcher(adapter, client, out, verbose=False, **kw)
        stats = fetcher.run()
        return out, client, stats

    @staticmethod
    def _manifest_rows(out):
        with open(out / "manifest.csv", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_path_uses_ext_album_and_records_license(self):
        item = MediaItem(
            url="http://h/x",
            title="The Raven",
            author="Poe",
            album="Poems",
            source="fake",
            ext="flac",
            license="public-domain",
        )
        out, client, stats = self._run([item])
        dest = out / "fake" / "Poe" / "Poems" / "The Raven.flac"
        self.assertTrue(dest.exists(), f"missing {dest}")
        self.assertEqual(stats.downloaded, 1)

        rows = self._manifest_rows(out)
        self.assertEqual(rows[0]["license"], "public-domain")
        self.assertEqual(rows[0]["album"], "Poems")
        self.assertEqual(rows[0]["status"], "downloaded")
        self.assertTrue(rows[0]["dest"].endswith("The Raven.flac"))

    def test_no_album_omits_middle_folder(self):
        item = MediaItem(url="http://h/y", title="Track", author="Artist",
                         source="fake", ext="mp3")
        out, client, stats = self._run([item])
        self.assertTrue((out / "fake" / "Artist" / "Track.mp3").exists())

    def test_skips_existing_file(self):
        item = MediaItem(url="http://h/z", title="T", author="A", source="fake")
        out, client, stats = self._run([item])
        self.assertEqual(stats.downloaded, 1)
        # Re-run against the same tree: should skip, not re-download.
        client2 = FakeClient({"page1": "body"})
        s2 = Fetcher(OnePageAdapter([item]), client2, out, verbose=False)
        stats2 = s2.run()
        self.assertEqual(stats2.skipped, 1)
        self.assertEqual(stats2.downloaded, 0)
        self.assertEqual(client2.downloaded, [])

    def test_dry_run_writes_no_audio(self):
        item = MediaItem(url="http://h/d", title="T", author="A", source="fake")
        out, client, stats = self._run([item], dry_run=True)
        self.assertEqual(client.downloaded, [])
        self.assertEqual(stats.downloaded, 0)
        rows = self._manifest_rows(out)
        self.assertEqual(rows[0]["status"], "dry-run")

    def test_dedupes_repeated_media_urls(self):
        dupe = MediaItem(url="http://h/same", title="T", author="A", source="fake")
        out, client, stats = self._run([dupe, dupe])
        self.assertEqual(stats.media_found, 1)

    def test_headers_hook_is_used_for_fetch(self):
        item = MediaItem(url="http://h/x", title="T", author="A", source="fake")
        out, client, stats = self._run([item], headers={"X-Auth": "z"})
        self.assertEqual(client.header_calls[0], ("page1", {"X-Auth": "z"}))


class TestParseSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_size("1000"), 1000)
        self.assertEqual(parse_size("500M"), 500 * 1024**2)
        self.assertEqual(parse_size("2G"), 2 * 1024**3)
        self.assertEqual(parse_size("750k"), 750 * 1024)
        self.assertEqual(parse_size("1.5G"), int(1.5 * 1024**3))
        self.assertEqual(parse_size("10MB"), 10 * 1024**2)  # trailing B ok

    def test_bad(self):
        with self.assertRaises(ValueError):
            parse_size("banana")


class TestRunCaps(unittest.TestCase):
    def _items(self, n):
        return [MediaItem(url=f"http://h/{i}", title=f"T{i}", author="A",
                          source="fake") for i in range(n)]

    def _run(self, items, **kw):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        client = FakeClient({"page1": "body"})
        stats = Fetcher(OnePageAdapter(items), client, out, verbose=False, **kw).run()
        return stats, client

    def test_limit_stops_after_n_downloads(self):
        stats, client = self._run(self._items(5), limit=2)
        self.assertEqual(stats.downloaded, 2)
        self.assertEqual(len(client.downloaded), 2)

    def test_max_bytes_stops_when_budget_spent(self):
        # FakeClient writes 27 bytes per file ("FAKEAUDIO"*3).
        stats, client = self._run(self._items(5), max_bytes=27)
        self.assertEqual(stats.downloaded, 1)

    def test_dry_run_ignores_caps(self):
        stats, client = self._run(self._items(5), limit=2, dry_run=True)
        self.assertEqual(stats.media_found, 5)  # discovery not capped in dry-run
        self.assertEqual(client.downloaded, [])


class FlakyClient(FakeClient):
    """Fails each URL's download `fail_first` times, then succeeds."""

    def __init__(self, pages, fail_first=1):
        super().__init__(pages)
        self.fail_first = fail_first
        self.attempts = {}

    def download(self, url, dest, headers=None):
        n = self.attempts.get(url, 0) + 1
        self.attempts[url] = n
        if n <= self.fail_first:
            raise ConnectionError("simulated network blip")
        return super().download(url, dest, headers=headers)


class TestDiscover(unittest.TestCase):
    def test_discovers_without_downloading(self):
        items = [MediaItem(url=f"http://h/{i}", title=f"T{i}", source="fake")
                 for i in range(3)]
        client = FakeClient({"page1": "body"})
        found = discover(OnePageAdapter(items), client, max_pages=10)
        self.assertEqual(len(found), 3)
        self.assertEqual(client.downloaded, [])  # discovery never downloads


class TestCacheWarmStart(unittest.TestCase):
    def test_cache_hit_skips_crawl(self):
        from open_audio_fetch.cache import AvailabilityCache
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out"
        cachedir = Path(tmp.name) / "cache"
        items = [MediaItem(url=f"http://h/{i}", title=f"T{i}", author="A",
                           source="fake") for i in range(3)]

        # First run: cache miss -> crawls (client.get_text called) + saves cache.
        c1 = FakeClient({"page1": "body"})
        cache = AvailabilityCache("fake", base_dir=cachedir)
        Fetcher(OnePageAdapter(items), c1, out, verbose=False, cache=cache).run()
        self.assertTrue(cache.path.exists())
        self.assertEqual(len(c1.header_calls), 1)  # it crawled

        # Second run into a fresh out dir: cache hit -> must NOT crawl.
        out2 = Path(tmp.name) / "out2"
        c2 = FakeClient({"page1": "body"})
        stats2 = Fetcher(OnePageAdapter(items), c2, out2, verbose=False,
                         cache=AvailabilityCache("fake", base_dir=cachedir)).run()
        self.assertEqual(c2.header_calls, [])        # crawl skipped entirely
        self.assertEqual(stats2.downloaded, 3)       # still downloaded from cache

    def test_refresh_forces_recrawl(self):
        from open_audio_fetch.cache import AvailabilityCache
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cachedir = Path(tmp.name) / "cache"
        items = [MediaItem(url="http://h/0", title="T", author="A", source="fake")]
        cache = AvailabilityCache("fake", base_dir=cachedir)
        Fetcher(OnePageAdapter(items), FakeClient({"page1": "b"}),
                Path(tmp.name) / "o1", verbose=False, cache=cache).run()
        c2 = FakeClient({"page1": "b"})
        Fetcher(OnePageAdapter(items), c2, Path(tmp.name) / "o2", verbose=False,
                cache=AvailabilityCache("fake", base_dir=cachedir), refresh=True).run()
        self.assertEqual(len(c2.header_calls), 1)    # --refresh re-crawled


class TestDedupe(unittest.TestCase):
    def test_key_normalizes(self):
        self.assertEqual(dedupe_key("Jane Austen", "Pride & Prejudice!"),
                         dedupe_key(" jane   austen ", "pride prejudice"))
        self.assertNotEqual(dedupe_key("A", "T1"), dedupe_key("A", "T2"))

    def test_dedupe_skips_second_same_work(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        # Same author+title, different URLs (as if from two sources).
        items = [
            MediaItem(url="http://a/x", title="Pride & Prejudice", author="Austen", source="s1"),
            MediaItem(url="http://b/y", title="pride prejudice", author="austen", source="s2"),
        ]
        stats = Fetcher(OnePageAdapter(items), FakeClient({"page1": "b"}), out,
                        verbose=False, dedupe=True).run()
        self.assertEqual(stats.downloaded, 1)
        self.assertEqual(stats.duplicates, 1)

    def test_dedupe_across_runs_via_manifest(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        item = MediaItem(url="http://a/x", title="The Raven", author="Poe", source="s1")
        Fetcher(OnePageAdapter([item]), FakeClient({"page1": "b"}), out,
                verbose=False, dedupe=True).run()
        # New run, same work from a different source URL + different filing.
        dup = MediaItem(url="http://b/y", title="the raven", author="poe", source="s2")
        stats = Fetcher(OnePageAdapter([dup]), FakeClient({"page1": "b"}), out,
                        verbose=False, dedupe=True).run()
        self.assertEqual(stats.downloaded, 0)
        self.assertEqual(stats.duplicates, 1)


class TestRetryPass(unittest.TestCase):
    def test_end_of_run_retry_recovers_failed_item(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        item = MediaItem(url="http://h/x", title="T", author="A", source="fake")
        client = FlakyClient({"page1": "body"}, fail_first=1)
        stats = Fetcher(OnePageAdapter([item]), client, out, verbose=False).run()
        # First attempt failed, the end-of-run retry pass recovered it.
        self.assertEqual(stats.downloaded, 1)
        self.assertEqual(stats.failed, 0)
        self.assertTrue((out / "fake" / "A" / "T.mp3").exists())
        self.assertEqual(client.attempts["http://h/x"], 2)

    def test_permanently_failing_item_stays_failed(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        item = MediaItem(url="http://h/x", title="T", author="A", source="fake")
        client = FlakyClient({"page1": "body"}, fail_first=99)
        stats = Fetcher(OnePageAdapter([item]), client, out, verbose=False).run()
        self.assertEqual(stats.downloaded, 0)
        self.assertEqual(stats.failed, 1)  # counted once, not doubled by the retry


if __name__ == "__main__":
    unittest.main()
