import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import _bootstrap  # noqa: F401

from open_audio_fetch.sites import get_adapter
from open_audio_fetch.sites.musopen import quota_after, quota_remaining


class EnvCase(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)


# -------------------------------------------------------------- listentogenius

LTG = """<h1>Edgar Allan Poe</h1>
<h2 class="wktit">Work: <span class="bigger">THE TELL-TALE HEART</span></h2>
<a href="recordings2/TellTaleHeart.mp3" target="_blank">alternate download link</a>"""


class TestListenToGenius(EnvCase):
    def test_extract_work(self):
        a = get_adapter("listentogenius")
        items = a.extract_media("https://listentogenius.com/author.php/1/2", LTG)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.author, "Edgar Allan Poe")
        self.assertEqual(it.title, "THE TELL-TALE HEART")
        self.assertEqual(it.ext, "mp3")
        self.assertEqual(it.license, "public-domain")
        self.assertTrue(it.url.endswith("recordings2/TellTaleHeart.mp3"))


# ----------------------------------------------------------------------- Lit2Go

LIT2GO = """<title>Chapter I: Down the Rabbit-Hole | Alice's Adventures in Wonderland | Lewis Carroll | Lit2Go ETC</title>
<h1>Lit 2 Go</h1>
<a href="/lit2go/books/">books</a>
<a href="https://etc.usf.edu/lit2go/audio/mp3/alice-001.mp3">audio</a>
<a href="https://etc.usf.edu/lit2go/data/alice.pdf">pdf</a>"""


class TestLit2Go(EnvCase):
    def test_grabs_mp3_skips_pdf_by_default(self):
        os.environ.pop("LIT2GO_PDF", None)
        a = get_adapter("lit2go")
        items = a.extract_media("https://etc.usf.edu/lit2go/1/alice/1/x/", LIT2GO)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.ext, "mp3")
        self.assertTrue(it.url.endswith("alice-001.mp3"))
        self.assertEqual(it.license, "public-domain")
        # Parsed from <title>, NOT the "Lit 2 Go" <h1> logo (which caused every
        # chapter to collide on the same filename).
        self.assertEqual(it.title, "Chapter I: Down the Rabbit-Hole")
        self.assertEqual(it.album, "Alice's Adventures in Wonderland")
        self.assertEqual(it.author, "Lewis Carroll")

    def test_pdf_included_when_opted_in(self):
        os.environ["LIT2GO_PDF"] = "1"
        a = get_adapter("lit2go")
        items = a.extract_media("https://etc.usf.edu/lit2go/1/oz/1/", LIT2GO)
        self.assertEqual({i.ext for i in items}, {"mp3", "pdf"})

    def test_follows_internal_links(self):
        a = get_adapter("lit2go")
        links = a.next_links("https://etc.usf.edu/lit2go/1/oz/1/", LIT2GO)
        self.assertIn("https://etc.usf.edu/lit2go/books/", links)


# -------------------------------------------------------------------------- FMA

FMA = """<title>Some Artist - Track</title>
<a href="https://freemusicarchive.org/track/foo/download">download</a>
<a rel="license" href="http://creativecommons.org/licenses/by-nc/4.0/">license</a>
<a href="/genre/Jazz">Jazz</a>"""


class TestFreeMusicArchive(EnvCase):
    def test_captures_download_and_cc_license(self):
        a = get_adapter("freemusicarchive")
        items = a.extract_media("https://freemusicarchive.org/genre/Jazz", FMA)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].url.endswith("/download"))
        self.assertEqual(items[0].license, "http://creativecommons.org/licenses/by-nc/4.0/")

    def test_follows_genre_links(self):
        a = get_adapter("freemusicarchive")
        links = a.next_links("https://freemusicarchive.org/genre/Jazz", FMA)
        self.assertIn("https://freemusicarchive.org/genre/Jazz", links)


# ------------------------------------------------------------------- LoyalBooks

LOYAL = """<title>Pride and Prejudice | Loyal Books</title>
<h1>Pride and Prejudice</h1>
<a href="/genre/Classics">Classics</a>
<a href="https://www.loyalbooks.com/download/mp3/pride_01.mp3">ch1</a>
<a href="https://www.loyalbooks.com/download/zip/pride.zip">zip</a>"""


class TestLoyalBooks(EnvCase):
    def test_chapter_and_zip(self):
        a = get_adapter("loyalbooks")
        items = a.extract_media("https://www.loyalbooks.com/book/pride", LOYAL)
        by_ext = {i.ext: i for i in items}
        self.assertIn("mp3", by_ext)
        self.assertIn("zip", by_ext)
        self.assertEqual(by_ext["mp3"].album, "Pride and Prejudice")
        self.assertEqual(by_ext["zip"].title, "Pride and Prejudice")
        self.assertEqual(by_ext["zip"].album, "")
        self.assertTrue(all(i.license == "public-domain" for i in items))


# --------------------------------------------------------------- Musopen quota

class TestMusopenQuota(unittest.TestCase):
    def test_remaining_fresh(self):
        self.assertEqual(quota_remaining({}, "2026-01-01", 5), 5)

    def test_remaining_used_today(self):
        st = {"date": "2026-01-01", "count": 5}
        self.assertEqual(quota_remaining(st, "2026-01-01", 5), 0)

    def test_rolls_over_next_day(self):
        st = {"date": "2026-01-01", "count": 5}
        self.assertEqual(quota_remaining(st, "2026-01-02", 5), 5)

    def test_quota_after_accumulates_same_day(self):
        st = quota_after({}, "2026-01-01", 3)
        self.assertEqual(st, {"date": "2026-01-01", "count": 3})
        st = quota_after(st, "2026-01-01", 2)
        self.assertEqual(st["count"], 5)
        self.assertEqual(quota_remaining(st, "2026-01-01", 5), 0)

    def test_quota_after_resets_on_new_day(self):
        st = {"date": "2026-01-01", "count": 4}
        self.assertEqual(quota_after(st, "2026-01-02", 1)["count"], 1)


MUSOPEN_HTML = """<h1>Beethoven</h1>
<a href="https://musopen.org/media/a1.mp3">1</a>
<a href="https://musopen.org/media/a2.mp3">2</a>
<a href="https://musopen.org/media/a3.mp3">3</a>"""


class TestMusopenGate(EnvCase):
    def _adapter(self, state_path, cap="2", dry=False):
        os.environ["MUSOPEN_STATE"] = str(state_path)
        os.environ["MUSOPEN_DAILY_CAP"] = cap
        if dry:
            os.environ["OPEN_AUDIO_FETCH_DRY_RUN"] = "1"
        else:
            os.environ.pop("OPEN_AUDIO_FETCH_DRY_RUN", None)
        return get_adapter("musopen")

    def test_hard_daily_cap_across_calls(self):
        with TemporaryDirectory() as d:
            state = Path(d) / "q.json"
            a = self._adapter(state, cap="2")
            first = a.extract_media("https://musopen.org/music/x", MUSOPEN_HTML)
            self.assertEqual(len(first), 2)  # capped even though 3 offered
            # Quota is now spent for the day: a fresh adapter must emit nothing.
            b = self._adapter(state, cap="2")
            second = b.extract_media("https://musopen.org/music/x", MUSOPEN_HTML)
            self.assertEqual(second, [])

    def test_dry_run_does_not_burn_quota(self):
        with TemporaryDirectory() as d:
            state = Path(d) / "q.json"
            a = self._adapter(state, cap="2", dry=True)
            a.extract_media("https://musopen.org/music/x", MUSOPEN_HTML)
            # Nothing persisted, so a real run still has full quota.
            b = self._adapter(state, cap="2")
            self.assertEqual(b._remaining(), 2)


if __name__ == "__main__":
    unittest.main()
