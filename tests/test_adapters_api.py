import json
import os
import unittest

import _bootstrap  # noqa: F401

from open_audio_fetch.sites import get_adapter


class EnvCase(unittest.TestCase):
    """Base that isolates os.environ so adapter __init__ config is hermetic."""

    def setUp(self):
        self._saved = dict(os.environ)
        for k in list(os.environ):
            if k.split("_")[0] in ("IA", "LIBRIVOX", "JAMENDO", "PODCASTINDEX", "LOC"):
                os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)


# --------------------------------------------------------------------------- IA

IA_SEARCH = json.dumps({
    "responseHeader": {"params": {"page": "1", "rows": "2"}},
    "response": {"numFound": 3, "start": 0,
                 "docs": [{"identifier": "itemA"}, {"identifier": "itemB"}]},
})

IA_META = json.dumps({
    "metadata": {
        "identifier": "itemA", "title": "Symphony No. 1", "creator": "Beethoven",
        "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/",
    },
    "files": [
        {"name": "track01.flac", "format": "Flac", "source": "original",
         "track": "1", "title": "Movement I"},
        {"name": "track01.mp3", "format": "VBR MP3", "source": "derivative",
         "track": "1", "title": "Movement I"},
        {"name": "track01.ogg", "format": "Ogg Vorbis", "source": "derivative"},
        {"name": "cover.jpg", "format": "JPEG"},
        {"name": "track02.mp3", "format": "VBR MP3", "track": "2",
         "title": "Movement II"},
    ],
})


class TestInternetArchive(EnvCase):
    def test_search_yields_metadata_urls_and_next_page(self):
        os.environ["IA_ROWS"] = "2"
        a = get_adapter("internetarchive")
        links = a.next_links(a._search_url(1), IA_SEARCH)
        self.assertIn("https://archive.org/metadata/itemA", links)
        self.assertIn("https://archive.org/metadata/itemB", links)
        self.assertTrue(any("page=2" in u for u in links))

    def test_max_items_caps_and_stops_paging(self):
        os.environ["IA_ROWS"] = "2"
        os.environ["IA_MAX_ITEMS"] = "1"
        a = get_adapter("internetarchive")
        links = a.next_links(a._search_url(1), IA_SEARCH)
        meta = [u for u in links if "/metadata/" in u]
        self.assertEqual(len(meta), 1)
        self.assertFalse(any("page=2" in u for u in links))

    def test_metadata_dedupes_formats_and_keeps_mp3(self):
        a = get_adapter("internetarchive")
        items = a.extract_media("https://archive.org/metadata/itemA", IA_META)
        self.assertEqual(len(items), 2)  # track01 (one format) + track02
        first = items[0]
        self.assertEqual(first.ext, "mp3")
        self.assertEqual(first.title, "01 Movement I")
        self.assertEqual(first.album, "Symphony No. 1")
        self.assertEqual(first.author, "Beethoven")
        self.assertTrue(first.url.endswith("/download/itemA/track01.mp3"))
        self.assertIn("publicdomain", first.license)
        self.assertEqual(items[1].title, "02 Movement II")

    def test_metadata_ignores_non_audio(self):
        a = get_adapter("internetarchive")
        items = a.extract_media("https://archive.org/metadata/itemA", IA_META)
        self.assertFalse(any(i.ext == "jpg" for i in items))

    def test_prefers_chapters_over_bundle(self):
        # An item shipping per-chapter MP3s AND a two-part M4B bundle.
        meta = json.dumps({
            "metadata": {"identifier": "bk", "title": "A Book", "creator": "Auth"},
            "files": [
                {"name": "book_01.mp3", "format": "VBR MP3", "track": "1", "title": "Ch 1"},
                {"name": "book_02.mp3", "format": "VBR MP3", "track": "2", "title": "Ch 2"},
                {"name": "BookPart1.m4b", "format": "Apple Audiobook"},
                {"name": "BookPart2.m4b", "format": "Apple Audiobook"},
            ],
        })
        a = get_adapter("internetarchive")  # default IA_PREFER=chapters
        items = a.extract_media("https://archive.org/metadata/bk", meta)
        self.assertEqual([i.ext for i in items], ["mp3", "mp3"])
        self.assertTrue(all("m4b" not in i.url for i in items))

    def test_prefer_bundle_keeps_only_m4b(self):
        os.environ["IA_PREFER"] = "bundle"
        meta = json.dumps({
            "metadata": {"identifier": "bk", "title": "A Book", "creator": "Auth"},
            "files": [
                {"name": "book_01.mp3", "format": "VBR MP3", "track": "1"},
                {"name": "BookPart1.m4b", "format": "Apple Audiobook"},
            ],
        })
        a = get_adapter("internetarchive")
        items = a.extract_media("https://archive.org/metadata/bk", meta)
        self.assertEqual([i.ext for i in items], ["m4b"])

    def test_only_exts_restricts_formats(self):
        # Force keeping FLAC only: track01 -> flac, track02 (mp3-only) -> dropped.
        os.environ["IA_ONLY_EXTS"] = "flac"
        a = get_adapter("internetarchive")
        items = a.extract_media("https://archive.org/metadata/itemA", IA_META)
        self.assertEqual([i.ext for i in items], ["flac"])
        self.assertTrue(items[0].url.endswith("track01.flac"))


# --------------------------------------------------------------------- LibriVox

LV_FEED = json.dumps({"books": [{
    "id": 1, "title": "Pride and Prejudice",
    "url_zip_file": "https://ia/pp_mp3.zip",
    "authors": [{"first_name": "Jane", "last_name": "Austen"}],
    "sections": [
        {"section_number": "1", "title": "Chapter 1", "listen_url": "https://ia/pp_01.mp3"},
        {"section_number": "2", "title": "Chapter 2", "listen_url": "https://ia/pp_02.mp3"},
    ],
}]})


class TestLibriVox(EnvCase):
    def test_zip_mode_default(self):
        a = get_adapter("librivox")
        items = a.extract_media(a.seeds()[0], LV_FEED)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it.ext, "zip")
        self.assertEqual(it.title, "Pride and Prejudice")
        self.assertEqual(it.author, "Jane Austen")
        self.assertEqual(it.license, "public-domain")
        self.assertEqual(it.album, "")

    def test_chapters_mode(self):
        os.environ["LIBRIVOX_MODE"] = "chapters"
        a = get_adapter("librivox")
        items = a.extract_media(a.seeds()[0], LV_FEED)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].album, "Pride and Prejudice")
        self.assertEqual(items[0].title, "01 Chapter 1")
        self.assertEqual(items[0].ext, "mp3")

    def test_pagination_when_page_full(self):
        os.environ["LIBRIVOX_LIMIT"] = "1"
        a = get_adapter("librivox")
        links = a.next_links(a.seeds()[0], LV_FEED)
        self.assertEqual(len(links), 1)
        self.assertIn("offset=1", links[0])


# ---------------------------------------------------------------------- Jamendo

JAMENDO = json.dumps({"headers": {"results_count": 3}, "results": [
    {"id": "1", "name": "Song A", "artist_name": "Artist X", "album_name": "Album Q",
     "audiodownload": "https://mp3d/1", "audiodownload_allowed": True,
     "license_ccurl": "http://creativecommons.org/licenses/by/3.0/"},
    {"id": "2", "name": "Song B", "artist_name": "Artist Y",
     "audiodownload": "https://mp3d/2", "audiodownload_allowed": True},
    {"id": "3", "name": "Blocked", "artist_name": "Z",
     "audiodownload": "https://mp3d/3", "audiodownload_allowed": False},
]})


class TestJamendo(EnvCase):
    def test_seeds_requires_client_id(self):
        a = get_adapter("jamendo")
        with self.assertRaises(RuntimeError):
            a.seeds()

    def test_seeds_ok_with_client_id(self):
        os.environ["JAMENDO_CLIENT_ID"] = "abc"
        a = get_adapter("jamendo")
        self.assertIn("client_id=abc", a.seeds()[0])

    def test_extract_captures_license_and_skips_disallowed(self):
        a = get_adapter("jamendo")
        items = a.extract_media("https://api.jamendo.com/v3.0/tracks/?x", JAMENDO)
        self.assertEqual(len(items), 2)  # blocked track excluded
        self.assertEqual(items[0].license, "http://creativecommons.org/licenses/by/3.0/")
        self.assertEqual(items[0].album, "Album Q")
        self.assertEqual(items[1].license, "creative-commons")  # fallback
        self.assertEqual(items[0].ext, "mp3")


# ----------------------------------------------------------------- PodcastIndex

PI_FEEDS = json.dumps({"feeds": [
    {"id": 1, "url": "https://feeds.example/show1.xml", "title": "Show One"},
    {"id": 2, "url": "https://feeds.example/show2.xml"},
]})

PI_RSS = """<rss><channel><title>Show One</title>
  <item><title>Episode 1</title>
    <enclosure url="https://cdn/ep1.mp3" type="audio/mpeg" length="1"/></item>
  <item><title>Episode 2</title>
    <enclosure url="https://cdn/ep2" type="audio/mp4" length="1"/></item>
</channel></rss>"""


class TestPodcastIndex(EnvCase):
    def test_headers_only_signed_for_api_host(self):
        os.environ["PODCASTINDEX_KEY"] = "K"
        os.environ["PODCASTINDEX_SECRET"] = "S"
        a = get_adapter("podcastindex")
        api = a.headers_for("https://api.podcastindex.org/api/1.0/search/byterm?q=x")
        self.assertEqual(api["X-Auth-Key"], "K")
        self.assertEqual(len(api["Authorization"]), 40)  # sha1 hexdigest
        self.assertEqual(a.headers_for("https://feeds.example/show1.xml"), {})

    def test_seeds_requires_credentials(self):
        a = get_adapter("podcastindex")
        with self.assertRaises(RuntimeError):
            a.seeds()

    def test_api_listing_yields_feed_urls(self):
        a = get_adapter("podcastindex")
        links = a.next_links(
            "https://api.podcastindex.org/api/1.0/podcasts/trending", PI_FEEDS
        )
        self.assertEqual(links, ["https://feeds.example/show1.xml",
                                 "https://feeds.example/show2.xml"])

    def test_rss_yields_episodes_with_show_folder(self):
        a = get_adapter("podcastindex")
        items = a.extract_media("https://feeds.example/show1.xml", PI_RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].author, "Show One")
        self.assertEqual(items[0].title, "Episode 1")
        self.assertEqual(items[0].ext, "mp3")
        self.assertEqual(items[1].ext, "m4a")  # inferred from audio/mp4
        self.assertIn("personal", items[0].license)

    def test_episode_cap(self):
        os.environ["PODCASTINDEX_MAX_EPISODES"] = "1"
        a = get_adapter("podcastindex")
        items = a.extract_media("https://feeds.example/show1.xml", PI_RSS)
        self.assertEqual(len(items), 1)

    def test_since_filters_old_episodes(self):
        os.environ["PODCASTINDEX_SINCE"] = "2026-01-10"
        feed = """<rss><channel><title>Show</title>
          <item><title>New</title><pubDate>Wed, 15 Jan 2026 00:00:00 GMT</pubDate>
            <enclosure url="https://cdn/new.mp3" type="audio/mpeg" length="1"/></item>
          <item><title>Old</title><pubDate>Fri, 01 Jan 2026 00:00:00 GMT</pubDate>
            <enclosure url="https://cdn/old.mp3" type="audio/mpeg" length="1"/></item>
        </channel></rss>"""
        a = get_adapter("podcastindex")
        items = a.extract_media("https://feeds.example/s.xml", feed)
        self.assertEqual([i.title for i in items], ["New"])


# --------------------------------------------------------------------------- LoC

LOC_COLL = json.dumps({
    "results": [
        {"id": "https://www.loc.gov/item/jukebox-1/", "title": "A Song"},
        {"id": "https://www.loc.gov/collections/x/"},
    ],
    "pagination": {"next": "https://www.loc.gov/collections/national-jukebox/?sp=2"},
})

LOC_ITEM = json.dumps({
    "item": {"title": "A Song", "rights_advisory": "Rights assessment required"},
    "resources": [{"files": [[
        {"url": "https://tile.loc.gov/storage/audio/a.mp3", "mimetype": "audio/mpeg"},
    ]]}],
})


class TestLoc(EnvCase):
    def test_collection_yields_item_and_next(self):
        a = get_adapter("loc")
        links = a.next_links(a.seeds()[0], LOC_COLL)
        self.assertTrue(any("/item/jukebox-1/" in u and "fo=json" in u for u in links))
        self.assertTrue(any("sp=2" in u for u in links))
        # A non-item result (a sub-collection) is not treated as an item.
        self.assertFalse(any("/collections/x/" in u for u in links))

    def test_item_finds_audio_recursively(self):
        a = get_adapter("loc")
        items = a.extract_media("https://www.loc.gov/item/jukebox-1/?fo=json", LOC_ITEM)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://tile.loc.gov/storage/audio/a.mp3")
        self.assertEqual(items[0].title, "A Song")
        self.assertEqual(items[0].license, "Rights assessment required")


if __name__ == "__main__":
    unittest.main()
