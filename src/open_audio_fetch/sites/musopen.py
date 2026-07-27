"""Adapter for Musopen — public-domain classical recordings, HARD rate-limited.

Musopen caps free downloads at roughly **5 per day**. This adapter treats that
as an absolute law, not an obstacle: it keeps a persistent daily counter on disk
and simply stops emitting once the day's quota is spent. It never parallelizes
around the limit, never rotates identities — a slow, honest trickle. That makes
it the natural fit for the scheduled runner (run it daily; it self-limits).

The quota bookkeeping is a pure, tested state machine (`quota_remaining`); the
page scraping around it is deliberately conservative and only follows freely
offered, no-login download links.

Config:
  MUSOPEN_DAILY_CAP  downloads allowed per day        (default: 5)
  MUSOPEN_STATE      path to the quota state json      (default: ~/.cache/…)
  MUSOPEN_START      comma list of browse start paths  (default: music/)
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import MediaItem, SiteAdapter, register
from ._helpers import env_int, env_list, env_str, ext_of, strip_tags

_BASE = "https://musopen.org/"

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_AUDIO_RE = re.compile(
    r"""["'(]\s*(https?://[^"'()\s]+?(?:\.mp3|\.flac|/download/?)[^"'()\s]*)\s*["')]""",
    re.I,
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)

_DEFAULT_STATE = "~/.cache/open-audio-fetch/musopen_quota.json"


def quota_remaining(state: dict, today: str, cap: int) -> int:
    """Downloads still allowed today, given persisted ``state``.

    Pure and total so it is trivial to unit-test. A state from an earlier day
    counts as zero used today (the quota rolls over at midnight).
    """
    used = state.get("count", 0) if state.get("date") == today else 0
    return max(0, cap - int(used))


def quota_after(state: dict, today: str, n: int) -> dict:
    """Return new state after recording ``n`` downloads on ``today``."""
    used = state.get("count", 0) if state.get("date") == today else 0
    return {"date": today, "count": int(used) + max(0, n)}


@register
class Musopen(SiteAdapter):
    name = "musopen"
    base_url = _BASE

    def __init__(self) -> None:
        self.cap = max(0, env_int("MUSOPEN_DAILY_CAP", 5))
        self.state_path = Path(
            os.path.expanduser(env_str("MUSOPEN_STATE", _DEFAULT_STATE))
        )
        self.starts = env_list("MUSOPEN_START", ("music/",))
        self._dry = os.environ.get("OPEN_AUDIO_FETCH_DRY_RUN") == "1"

    # -- persistent quota ----------------------------------------------------

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state))
        except OSError:
            pass  # never let quota bookkeeping crash a run

    def _remaining(self) -> int:
        return quota_remaining(self._load(), self._today(), self.cap)

    def _consume(self, n: int) -> None:
        if n <= 0 or self._dry:
            return  # dry runs must not burn the real daily quota
        self._save(quota_after(self._load(), self._today(), n))

    # -- crawl ---------------------------------------------------------------

    def seeds(self) -> list[str]:
        return [urljoin(_BASE, s) for s in self.starts]

    def next_links(self, page_url: str, html: str) -> list[str]:
        # No point crawling further once today's quota is exhausted.
        if self._remaining() <= 0:
            return []
        links: list[str] = []
        for href in _HREF_RE.findall(html):
            absu = urljoin(page_url, href.strip()).split("#", 1)[0]
            parts = urlsplit(absu)
            if parts.netloc.endswith("musopen.org") and "/music/" in parts.path:
                if not parts.path.lower().endswith((".mp3", ".flac")):
                    links.append(absu)
        return links

    def extract_media(self, page_url: str, html: str) -> list[MediaItem]:
        remaining = self._remaining()
        if remaining <= 0:
            return []

        urls = list(dict.fromkeys(_AUDIO_RE.findall(html)))
        if not urls:
            return []

        heading = ""
        m = _H1_RE.search(html)
        if m:
            heading = strip_tags(m.group(1))

        items: list[MediaItem] = []
        for url in urls[:remaining]:
            ext = ext_of(url) or "mp3"
            stem = re.sub(r"\.[^.]+$", "", url.rstrip("/").rsplit("/", 1)[-1]) or heading
            items.append(
                MediaItem(
                    url=url,
                    title=heading or stem or "Untitled",
                    author="Various",
                    source=self.name,
                    ext=ext,
                    license="public-domain",
                )
            )
        # Reserve quota for exactly what we handed the engine to download.
        self._consume(len(items))
        return items
