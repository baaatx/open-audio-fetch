"""A small, polite HTTP client built on the standard library only.

No third-party dependencies so the tool runs anywhere Python does. It adds the
manners that separate a considerate downloader from an abusive one: an honest
User-Agent, a fixed inter-request delay, per-host robots.txt enforcement, and
retries that tell the difference between a permanent error, a transient blip,
and a full network outage.

Resilience is the point of a bulk downloader: a dropped connection mid-run must
not abort the job. So fetches are classified:

  * permanent (HTTP 404/403/…, wrong content type) — fail fast, no retry;
  * transient (HTTP 5xx/429, timeouts) — a few backed-off retries;
  * outage    (DNS failure, connection refused/reset, network unreachable) —
               *wait for the network to come back*, polling with exponential
               backoff up to ``max_outage_wait`` before giving up.

That last case is what lets a pull survive a router reboot or a Wi-Fi hiccup and
finish on its own.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from http.client import IncompleteRead
from urllib.parse import urlsplit

USER_AGENT = (
    "open-audio-fetch/0.1 (+https://github.com/; respectful free-audio fetcher)"
)

# HTTP status codes where retrying cannot help — the request itself is the
# problem, not the connection.
_PERMANENT_HTTP = frozenset({400, 401, 403, 404, 405, 406, 410, 451})

# Error classification results.
PERMANENT, TRANSIENT, OUTAGE = "permanent", "transient", "outage"

# RFC 3986 reserved + sub-delims we must NOT re-encode, plus '%' so an
# already-encoded URL is not double-encoded. Everything else unsafe (spaces,
# quotes, non-ASCII) gets percent-encoded. This is what fixes source URLs like
# archive.org's `.../formats=64KBPS MP3&file=...` that carry a raw space.
_URL_SAFE = "%/:@?#[]!$&'()*+,;=~"


class IncompleteDownload(Exception):
    """Bytes written did not match the server's Content-Length — retry it."""


def encode_url(url: str) -> str:
    """Percent-encode unsafe characters in `url` without breaking its structure
    or double-encoding existing %xx escapes."""
    from urllib.parse import quote

    return quote(url, safe=_URL_SAFE)


def classify_error(err: BaseException) -> str:
    """Bucket a fetch exception into PERMANENT / TRANSIENT / OUTAGE.

    Kept module-level and pure so it is easy to unit-test the policy directly.
    """
    # A short/truncated download should be retried, not treated as done.
    if isinstance(err, IncompleteDownload):
        return TRANSIENT
    # Our own "this isn't audio" rejection — retrying an error page won't help.
    if isinstance(err, ValueError):
        return PERMANENT
    # HTTPError is a subclass of URLError, so test it first.
    if isinstance(err, urllib.error.HTTPError):
        return PERMANENT if err.code in _PERMANENT_HTTP else TRANSIENT
    # DNS resolution failure — the classic "network just dropped" signal.
    if isinstance(err, socket.gaierror):
        return OUTAGE
    if isinstance(err, urllib.error.URLError):
        reason = err.reason
        if isinstance(reason, socket.gaierror):
            return OUTAGE
        if isinstance(reason, TimeoutError):
            return TRANSIENT
        if isinstance(reason, OSError):
            # connection refused/reset, network/host unreachable, …
            return OUTAGE
        return TRANSIENT
    if isinstance(err, TimeoutError):
        return TRANSIENT
    if isinstance(err, ConnectionError):
        return OUTAGE
    if isinstance(err, OSError):
        return OUTAGE
    return TRANSIENT


@dataclass
class PoliteClient:
    """Rate-limited, robots-aware HTTP client.

    Args:
        delay: minimum seconds between requests to the same host.
        timeout: per-request socket timeout in seconds.
        retries: retry attempts on *transient* failures (5xx/429/timeout).
        obey_robots: when True, refuse to fetch paths disallowed by robots.txt.
        max_backoff: cap on any single backoff sleep, in seconds.
        max_outage_wait: total seconds to keep waiting through a network *outage*
            (DNS/connection down) for one request before giving up. Outage waits
            do not count against ``retries`` — a long outage just pauses us.
    """

    delay: float = 1.0
    timeout: float = 30.0
    retries: int = 3
    obey_robots: bool = True
    user_agent: str = USER_AGENT
    max_backoff: float = 60.0
    max_outage_wait: float = 600.0

    _last_request: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(
        default_factory=dict
    )

    # -- robots ---------------------------------------------------------------

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{host}/robots.txt")
        try:
            rp.read()
        except Exception:
            # If robots.txt cannot be read, be conservative but not paralyzed:
            # treat as "no rules" (the RFC's default) rather than blocking all.
            rp = None
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        rp = self._robots_for(url)
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    # -- pacing ---------------------------------------------------------------

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _request(
        self, url: str, extra_headers: dict[str, str] | None = None
    ) -> urllib.request.Request:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            # Ask for an uncompressed body so urllib does not have to
            # decode gzip/deflate itself.
            "Accept-Encoding": "identity",
        }
        if extra_headers:
            headers.update(extra_headers)
        return urllib.request.Request(encode_url(url), headers=headers)

    # -- fetching -------------------------------------------------------------

    def get_text(
        self,
        url: str,
        encoding: str = "utf-8",
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Fetch a URL and return its body decoded as text."""
        data = self._get_bytes(url, headers=headers)
        return data.decode(encoding, errors="replace")

    def _get_bytes(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> bytes:
        def read_body(resp):
            try:
                return resp.read()
            except IncompleteRead as err:
                # Some servers (e.g. etc.usf.edu) truncate a large page. For a
                # text/HTML crawl the bytes that DID arrive still carry the links
                # we need, so salvage them rather than failing the whole page.
                return err.partial

        return self._resilient(url, headers, read_body, what="fetch")

    def download(self, url: str, dest, *, reject_text: bool = True, headers=None):
        """Stream `url` to path `dest`, writing to a temp file then renaming.

        Returns the number of bytes written. Raises on robots/HTTP/type errors.
        When `reject_text` is True, a text/html body (typically an error page
        served with a 200) is refused rather than saved as a bogus audio file.
        Survives network outages (see `_resilient`); a stream that breaks
        mid-download discards the partial `.part` and retries.
        """
        import shutil

        dest = _as_path(dest)
        tmp = dest.with_suffix(dest.suffix + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)

        def handle(resp):
            ctype = resp.headers.get("Content-Type", "")
            if reject_text and ctype.lower().startswith(("text/", "application/xhtml")):
                raise ValueError(f"expected audio but got {ctype!r} for {url}")
            try:
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(resp, fh, length=64 * 1024)
                written = tmp.stat().st_size
                # Integrity: if the server told us how big the file is, insist we
                # got all of it. A short read (dropped connection) is retryable,
                # never silently accepted as a finished download.
                expected = resp.headers.get("Content-Length")
                if expected is not None and expected.strip().isdigit():
                    want = int(expected)
                    if written != want:
                        raise IncompleteDownload(
                            f"{url}: got {written} of {want} bytes"
                        )
                tmp.replace(dest)
                return written
            except BaseException:
                # A broken/short stream leaves no half file behind; the driver
                # decides whether to retry.
                tmp.unlink(missing_ok=True)
                raise

        return self._resilient(url, headers, handle, what="download")

    def probe(self, url, *, headers=None) -> tuple[bool, str]:
        """Lightweight reachability check for `--doctor`: open the URL, read one
        byte, report (ok, detail). Robots-aware; does not download the body."""
        if not self.allowed(url):
            return (False, "robots-disallow")
        try:
            self._throttle(url)
            with urllib.request.urlopen(
                self._request(url, headers), timeout=self.timeout
            ) as resp:
                resp.read(1)
                return (True, f"HTTP {getattr(resp, 'status', 200)}")
        except urllib.error.HTTPError as err:
            return (False, f"HTTP {err.code}")
        except Exception as err:  # noqa: BLE001
            return (False, type(err).__name__)

    # -- resilient retry driver ----------------------------------------------

    def _resilient(self, url, headers, handle, *, what):
        """Fetch `url` and pass the response to `handle`, retrying intelligently.

        Permanent errors fail immediately; transient errors get `retries`
        backed-off attempts; a network outage pauses (polling with exponential
        backoff) until the connection returns or `max_outage_wait` is exceeded.
        """
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows fetching: {url}")

        transient_left = self.retries
        outage_waited = 0.0
        backoff = max(self.delay, 1.0)
        last_err: BaseException | None = None

        while True:
            self._throttle(url)
            try:
                with urllib.request.urlopen(
                    self._request(url, headers), timeout=self.timeout
                ) as resp:
                    return handle(resp)
            except PermissionError:
                raise
            except BaseException as err:  # noqa: BLE001 — classified below
                last_err = err
                kind = classify_error(err)
                if kind == PERMANENT:
                    raise ConnectionError(f"failed to {what} {url}: {err}") from err

                wait = min(backoff, self.max_backoff)
                backoff *= 2
                if kind == OUTAGE:
                    if outage_waited >= self.max_outage_wait:
                        raise ConnectionError(
                            f"network down; gave up trying to {what} {url} after "
                            f"{outage_waited:.0f}s: {err}"
                        ) from err
                    # Waiting out an outage does NOT spend the transient budget.
                    time.sleep(wait)
                    outage_waited += wait
                else:  # TRANSIENT
                    transient_left -= 1
                    if transient_left <= 0:
                        raise ConnectionError(
                            f"failed to {what} {url}: {err}"
                        ) from err
                    time.sleep(wait)


def _as_path(p):
    from pathlib import Path

    return p if isinstance(p, __import__("pathlib").Path) else Path(p)
