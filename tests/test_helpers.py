import os
import unittest

import _bootstrap  # noqa: F401

from open_audio_fetch.sites import _helpers as h


class TestText(unittest.TestCase):
    def test_strip_tags_unescapes_and_collapses(self):
        self.assertEqual(h.strip_tags("<h1>Hi   &amp;  <b>bye</b></h1>"), "Hi & bye")
        self.assertEqual(h.strip_tags(""), "")


class TestFormats(unittest.TestCase):
    def test_ext_of(self):
        self.assertEqual(h.ext_of("foo/Bar.MP3"), "mp3")
        self.assertEqual(h.ext_of("http://x/y.flac?a=1&b=2"), "flac")
        self.assertEqual(h.ext_of("http://x/download/"), "")
        self.assertEqual(h.ext_of("noextension"), "")

    def test_is_audio(self):
        self.assertTrue(h.is_audio("song.ogg"))
        self.assertTrue(h.is_audio("http://x/y.m4b"))
        self.assertFalse(h.is_audio("cover.jpg"))
        self.assertFalse(h.is_audio("meta.xml"))

    def test_format_rank_prefers_mp3_over_flac(self):
        self.assertLess(h.format_rank("mp3"), h.format_rank("flac"))
        self.assertEqual(h.format_rank("weird"), len(h.FORMAT_PREFERENCE))

    def test_pick_best_by_format(self):
        best = h.pick_best_by_format([("flac", "F"), ("mp3", "M"), ("ogg", "O")])
        self.assertEqual(best, ("mp3", "M"))
        self.assertIsNone(h.pick_best_by_format([]))

    def test_pick_best_respects_custom_preference(self):
        best = h.pick_best_by_format(
            [("mp3", "M"), ("flac", "F")], preference=("flac", "mp3")
        )
        self.assertEqual(best, ("flac", "F"))


class TestRss(unittest.TestCase):
    FEED = """<rss><channel><title>My Show</title>
      <item><title>Ep 1</title>
        <enclosure url="http://h/ep1.mp3" length="123" type="audio/mpeg"/></item>
      <item><title>Ep 2</title>
        <enclosure url="http://h/ep2.m4a" type="audio/mp4" length="9"/></item>
    </channel></rss>"""

    def test_rss_items_and_enclosures(self):
        items = h.rss_items(self.FEED)
        self.assertEqual(len(items), 2)
        enc = h.rss_enclosures(self.FEED)
        self.assertEqual(enc[0]["url"], "http://h/ep1.mp3")
        self.assertEqual(enc[0]["type"], "audio/mpeg")
        self.assertEqual(enc[1]["url"], "http://h/ep2.m4a")

    def test_first_title(self):
        self.assertEqual(h.first_title("<item><title>Ep &amp; 1</title></item>"), "Ep & 1")


class TestEnv(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_env_int(self):
        os.environ["X_INT"] = "42"
        self.assertEqual(h.env_int("X_INT", 1), 42)
        os.environ["X_INT"] = "notanint"
        self.assertEqual(h.env_int("X_INT", 7), 7)
        os.environ.pop("X_INT", None)
        self.assertEqual(h.env_int("X_INT", 5), 5)

    def test_env_list(self):
        os.environ["X_LIST"] = "a, b ,,c"
        self.assertEqual(h.env_list("X_LIST"), ("a", "b", "c"))
        os.environ.pop("X_LIST", None)
        self.assertEqual(h.env_list("X_LIST", ("d",)), ("d",))

    def test_env_str_strips(self):
        os.environ["X_STR"] = "  hi  "
        self.assertEqual(h.env_str("X_STR"), "hi")


if __name__ == "__main__":
    unittest.main()
