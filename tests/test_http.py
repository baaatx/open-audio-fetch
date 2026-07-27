import io
import socket
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

import _bootstrap  # noqa: F401

from open_audio_fetch import http
from open_audio_fetch.http import (
    OUTAGE,
    PERMANENT,
    TRANSIENT,
    IncompleteDownload,
    PoliteClient,
    classify_error,
    encode_url,
)


class FakeResp(io.BytesIO):
    def __init__(self, data=b"", ctype="application/octet-stream"):
        super().__init__(data)
        self.headers = {"Content-Type": ctype}


def _http_error(code):
    # Give it a real (empty) body and close it so the file-like HTTPError does
    # not emit a ResourceWarning when garbage-collected. Only `.code` matters
    # to classification and the retry driver.
    err = urllib.error.HTTPError("http://h/x", code, "err", {}, io.BytesIO(b""))
    err.close()
    return err


class TestClassify(unittest.TestCase):
    def test_permanent_http(self):
        self.assertEqual(classify_error(_http_error(404)), PERMANENT)
        self.assertEqual(classify_error(_http_error(403)), PERMANENT)

    def test_transient_http(self):
        self.assertEqual(classify_error(_http_error(503)), TRANSIENT)
        self.assertEqual(classify_error(_http_error(429)), TRANSIENT)

    def test_dns_failure_is_outage(self):
        gai = socket.gaierror(8, "nodename nor servname provided, or not known")
        self.assertEqual(classify_error(gai), OUTAGE)
        self.assertEqual(classify_error(urllib.error.URLError(gai)), OUTAGE)

    def test_connection_and_timeout(self):
        self.assertEqual(classify_error(ConnectionResetError()), OUTAGE)
        self.assertEqual(classify_error(TimeoutError()), TRANSIENT)
        self.assertEqual(
            classify_error(urllib.error.URLError(TimeoutError())), TRANSIENT
        )

    def test_content_type_rejection_is_permanent(self):
        self.assertEqual(classify_error(ValueError("not audio")), PERMANENT)


class TestRequestHeaders(unittest.TestCase):
    def test_request_carries_ua_and_extra_headers(self):
        c = PoliteClient()
        req = c._request("http://x/y", {"Token": "abc"})
        self.assertIn("open-audio-fetch", req.get_header("User-agent"))
        self.assertEqual(req.get_header("Accept-encoding"), "identity")
        self.assertEqual(req.get_header("Token"), "abc")


class TestUrlEncoding(unittest.TestCase):
    def test_encodes_spaces_preserving_structure(self):
        raw = "https://archive.org/compress/x/formats=64KBPS MP3&file=/x.zip"
        enc = encode_url(raw)
        self.assertNotIn(" ", enc)
        self.assertIn("%20", enc)
        self.assertIn("&file=", enc)      # query delimiters preserved
        self.assertTrue(enc.startswith("https://archive.org/"))

    def test_does_not_double_encode(self):
        self.assertEqual(encode_url("https://h/a%20b.mp3"), "https://h/a%20b.mp3")

    def test_request_uses_encoded_url(self):
        c = PoliteClient()
        req = c._request("https://h/a b.mp3")
        self.assertIn("%20", req.full_url)
        self.assertNotIn(" ", req.full_url)


class TestIntegrity(unittest.TestCase):
    def test_incomplete_download_is_transient(self):
        self.assertEqual(classify_error(IncompleteDownload("short")), TRANSIENT)


class TestRobots(unittest.TestCase):
    def test_ignore_robots_never_touches_network(self):
        c = PoliteClient(obey_robots=False)
        # Would raise if it tried to fetch robots.txt; it must not.
        self.assertTrue(c.allowed("http://any.example/whatever"))


class TestThrottle(unittest.TestCase):
    def test_waits_remaining_time(self):
        c = PoliteClient(delay=2.0)
        clock = {"t": 0.0}
        slept = []
        orig_mono, orig_sleep = http.time.monotonic, http.time.sleep
        http.time.monotonic = lambda: clock["t"]
        http.time.sleep = lambda s: slept.append(s)
        try:
            c._throttle("http://h/a")
            clock["t"] += 0.5
            c._throttle("http://h/a")
        finally:
            http.time.monotonic, http.time.sleep = orig_mono, orig_sleep
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 1.5, places=6)


class TestFetchAndDownload(unittest.TestCase):
    def _patch_urlopen(self, resp):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["headers"] = dict(req.header_items())
            return resp

        orig = http.urllib.request.urlopen
        http.urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(http.urllib.request, "urlopen", orig))
        return seen

    def test_get_text_decodes_body(self):
        seen = self._patch_urlopen(FakeResp(b'{"ok": true}', "application/json"))
        c = PoliteClient(delay=0, obey_robots=False)
        self.assertEqual(c.get_text("http://h/x"), '{"ok": true}')

    def test_download_rejects_html(self):
        self._patch_urlopen(FakeResp(b"<html>oops</html>", "text/html"))
        c = PoliteClient(delay=0, obey_robots=False, retries=1)
        with TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                c.download("http://h/x.mp3", Path(d) / "a.mp3")

    def test_download_writes_audio_and_returns_size(self):
        payload = b"ID3AUDIOBYTES" * 4
        self._patch_urlopen(FakeResp(payload, "audio/mpeg"))
        c = PoliteClient(delay=0, obey_robots=False)
        with TemporaryDirectory() as d:
            dest = Path(d) / "song.mp3"
            n = c.download("http://h/song.mp3", dest)
            self.assertEqual(n, len(payload))
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(dest.with_suffix(".mp3.part").exists())

    def test_download_passes_auth_headers(self):
        seen = self._patch_urlopen(FakeResp(b"x", "audio/mpeg"))
        c = PoliteClient(delay=0, obey_robots=False)
        with TemporaryDirectory() as d:
            c.download("http://h/x.mp3", Path(d) / "x.mp3", headers={"X-Auth-Key": "k"})
        self.assertEqual(seen["headers"].get("X-auth-key"), "k")


class TestResilience(unittest.TestCase):
    """The self-healing retry behavior: outage-waiting, no-retry, backoff."""

    def _patch_sequence(self, actions):
        """Each urlopen call raises (if an exception) or returns the next action."""
        it = iter(actions)
        slept = []

        def fake_urlopen(req, timeout=None):
            a = next(it)
            if isinstance(a, BaseException):
                raise a
            return a

        orig_open = http.urllib.request.urlopen
        orig_sleep = http.time.sleep
        http.urllib.request.urlopen = fake_urlopen
        http.time.sleep = lambda s: slept.append(s)
        self.addCleanup(lambda: setattr(http.urllib.request, "urlopen", orig_open))
        self.addCleanup(lambda: setattr(http.time, "sleep", orig_sleep))
        return slept

    def test_outage_waits_then_succeeds(self):
        gai = urllib.error.URLError(socket.gaierror(8, "nodename"))
        slept = self._patch_sequence([gai, gai, gai, FakeResp(b"ok", "application/json")])
        c = PoliteClient(delay=0, obey_robots=False, retries=3)
        self.assertEqual(c.get_text("http://h/x"), "ok")
        # It waited out three outage failures — more than the transient budget —
        # proving outage waits don't count against `retries`.
        self.assertEqual(len(slept), 3)

    def test_permanent_error_fails_fast_without_sleeping(self):
        slept = self._patch_sequence([_http_error(404)])
        c = PoliteClient(delay=0, obey_robots=False, retries=3)
        with self.assertRaises(ConnectionError):
            c.get_text("http://h/missing")
        self.assertEqual(slept, [])  # no retries, no backoff

    def test_transient_exhausts_budget(self):
        slept = self._patch_sequence([_http_error(503)] * 5)
        c = PoliteClient(delay=0, obey_robots=False, retries=2)
        with self.assertRaises(ConnectionError):
            c.get_text("http://h/flaky")
        self.assertEqual(len(slept), 1)  # 2 attempts => 1 backoff between them

    def test_outage_gives_up_after_max_wait(self):
        gai = urllib.error.URLError(socket.gaierror(8, "nodename"))
        self._patch_sequence([gai] * 20)
        c = PoliteClient(delay=0, obey_robots=False, max_outage_wait=5)
        with self.assertRaises(ConnectionError) as ctx:
            c.get_text("http://h/down")
        self.assertIn("network down", str(ctx.exception))

    def test_truncated_download_retries_then_succeeds(self):
        short = FakeResp(b"AB", "audio/mpeg")
        short.headers["Content-Length"] = "10"
        full = FakeResp(b"ABCDEFGHIJ", "audio/mpeg")
        full.headers["Content-Length"] = "10"
        self._patch_sequence([short, full])
        c = PoliteClient(delay=0, obey_robots=False)
        with TemporaryDirectory() as d:
            dest = Path(d) / "x.mp3"
            n = c.download("http://h/x.mp3", dest)
            self.assertEqual(n, 10)
            self.assertEqual(dest.read_bytes(), b"ABCDEFGHIJ")

    def test_persistently_truncated_download_fails(self):
        def short():
            r = FakeResp(b"AB", "audio/mpeg")
            r.headers["Content-Length"] = "10"
            return r
        self._patch_sequence([short(), short(), short(), short()])
        c = PoliteClient(delay=0, obey_robots=False, retries=2)
        with TemporaryDirectory() as d:
            with self.assertRaises(ConnectionError):
                c.download("http://h/x.mp3", Path(d) / "x.mp3")
            self.assertFalse((Path(d) / "x.mp3").exists())

    def test_download_recovers_from_broken_connection(self):
        payload = b"AUDIO" * 10
        self._patch_sequence([ConnectionResetError("reset"),
                              FakeResp(payload, "audio/mpeg")])
        c = PoliteClient(delay=0, obey_robots=False)
        with TemporaryDirectory() as d:
            dest = Path(d) / "song.mp3"
            n = c.download("http://h/song.mp3", dest)
            self.assertEqual(n, len(payload))
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(dest.with_suffix(".mp3.part").exists())


if __name__ == "__main__":
    unittest.main()
