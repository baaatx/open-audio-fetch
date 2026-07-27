"""Adapter for Podcast Index — open podcast database, two-stage crawl.

Stage 1 hits the authenticated Podcast Index API (search or trending) to get
podcast *feeds*. Stage 2 fetches each feed's RSS and reads its ``<enclosure>``
tags for episode audio. The API requires a per-request auth signature —
``sha1(key + secret + unix_time)`` — which we supply through the adapter's
``headers_for`` hook (only for API calls; the RSS feeds themselves are public).

Podcasts are offered for **personal listening**, not redistribution, so the
license is recorded as such. Per-feed episode caps keep a run bounded.

Config:
  PODCASTINDEX_KEY           required — API key
  PODCASTINDEX_SECRET        required — API secret
  PODCASTINDEX_QUERY         search term; empty -> trending  (default: "")
  PODCASTINDEX_MAX_FEEDS     shows to pull        (default: 20)
  PODCASTINDEX_MAX_EPISODES  episodes per show    (default: 10)
  PODCASTINDEX_SINCE         YYYY-MM-DD; only episodes published on/after this
                             (new-episodes-only, for the scheduled trickle)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit

from . import MediaItem, SiteAdapter, register
from ._helpers import env_int, env_str, ext_of, rss_enclosures, rss_items, strip_tags

_API_HOST = "api.podcastindex.org"
_API = f"https://{_API_HOST}/api/1.0"

_CHANNEL_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_PUBDATE_RE = re.compile(r"<pubDate>(.*?)</pubDate>", re.I | re.S)


def _episode_date(chunk: str):
    """Parse an RSS <pubDate> to a date, or None if absent/unparseable."""
    m = _PUBDATE_RE.search(chunk)
    if not m:
        return None
    try:
        return parsedate_to_datetime(m.group(1).strip()).date()
    except (TypeError, ValueError):
        return None


def _parse_since(text: str):
    """Parse a YYYY-MM-DD 'since' filter, or None if unset/invalid."""
    if not text:
        return None
    try:
        y, mth, d = (int(x) for x in text.split("-"))
        return date(y, mth, d)
    except (ValueError, TypeError):
        return None
_TYPE_TO_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def _enclosure_ext(url: str, mime: str) -> str:
    ext = ext_of(url)
    if ext in ("mp3", "m4a", "m4b", "ogg", "opus", "aac", "flac", "wav"):
        return ext
    return _TYPE_TO_EXT.get(mime.lower().split(";")[0].strip(), "mp3")


@register
class PodcastIndex(SiteAdapter):
    name = "podcastindex"
    base_url = "https://podcastindex.org/"

    def __init__(self) -> None:
        self.key = env_str("PODCASTINDEX_KEY")
        self.secret = env_str("PODCASTINDEX_SECRET")
        self.query = env_str("PODCASTINDEX_QUERY")
        self.max_feeds = max(1, env_int("PODCASTINDEX_MAX_FEEDS", 20))
        self.max_episodes = max(1, env_int("PODCASTINDEX_MAX_EPISODES", 10))
        self.since = _parse_since(env_str("PODCASTINDEX_SINCE"))  # new-episodes-only
        self._feeds = 0

    # -- auth ----------------------------------------------------------------

    def headers_for(self, url: str) -> dict[str, str]:
        if urlsplit(url).netloc != _API_HOST:
            return {}  # public RSS feeds need no signature
        now = str(int(time.time()))
        digest = hashlib.sha1((self.key + self.secret + now).encode()).hexdigest()
        return {
            "X-Auth-Key": self.key,
            "X-Auth-Date": now,
            "Authorization": digest,
        }

    # -- crawl ---------------------------------------------------------------

    def seeds(self) -> list[str]:
        if not (self.key and self.secret):
            raise RuntimeError(
                "Podcast Index needs credentials: set PODCASTINDEX_KEY and "
                "PODCASTINDEX_SECRET (free at https://api.podcastindex.org)."
            )
        if self.query:
            return [f"{_API}/search/byterm?{urlencode({'q': self.query, 'max': self.max_feeds})}"]
        return [f"{_API}/podcasts/trending?{urlencode({'max': self.max_feeds})}"]

    def next_links(self, page_url: str, body: str) -> list[str]:
        if urlsplit(page_url).netloc != _API_HOST:
            return []  # an RSS feed: leaf
        try:
            feeds = json.loads(body).get("feeds", []) or []
        except ValueError:
            return []
        links: list[str] = []
        for feed in feeds:
            if self._feeds >= self.max_feeds:
                break
            rss = feed.get("url")
            if rss:
                self._feeds += 1
                links.append(rss)
        return links

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        if urlsplit(page_url).netloc == _API_HOST:
            return []  # API listing carries no downloadable media itself

        # An RSS feed: channel title becomes the show folder.
        m = _CHANNEL_TITLE_RE.search(body)
        show = strip_tags(m.group(1)) if m else "Podcast"

        items: list[MediaItem] = []
        for chunk in rss_items(body):
            if len(items) >= self.max_episodes:
                break
            # New-episodes-only: skip anything published before --since.
            if self.since is not None:
                ep_date = _episode_date(chunk)
                if ep_date is not None and ep_date < self.since:
                    continue
            encs = rss_enclosures(chunk)
            if not encs:
                continue
            enc = encs[0]
            url = enc["url"]
            tm = _CHANNEL_TITLE_RE.search(chunk)  # first <title> inside the item
            ep_title = strip_tags(tm.group(1)) if tm else "Episode"
            items.append(
                MediaItem(
                    url=url,
                    title=ep_title or "Episode",
                    author=show,
                    source=self.name,
                    ext=_enclosure_ext(url, enc.get("type", "")),
                    license="free-personal (do not redistribute)",
                )
            )
        return items
