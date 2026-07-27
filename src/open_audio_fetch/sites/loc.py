"""Adapter for the Library of Congress — National Jukebox & audio (JSON API).

Every loc.gov page has a JSON view via ``?fo=json``. We list a collection, walk
each item's JSON, and pull out downloadable audio. LoC's JSON is deeply nested
and its shape drifts between collections, so instead of hard-coding a path we
recursively scan an item's JSON for audio URLs — robust to layout changes.

Rights on LoC vary per item (many National Jukebox recordings carry access
conditions), so we record each item's stated rights.

Config:
  LOC_COLLECTION  collection slug   (default: national-jukebox)
  LOC_QUERY       full search URL, overrides LOC_COLLECTION
  LOC_MAX_ITEMS   cap on items processed (default: 100)
"""

from __future__ import annotations

import json
import re

from . import MediaItem, SiteAdapter, register
from ._helpers import env_int, env_str, ext_of

_AUDIO_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:mp3|m4a|ogg|flac|wav)(?:\?[^\s\"'<>]*)?", re.I
)


def _with_json(url: str) -> str:
    if "fo=json" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}fo=json"


def _find_audio_urls(node) -> list[str]:
    """Depth-first collect every audio-looking URL string in a JSON tree."""
    found: list[str] = []
    if isinstance(node, str):
        found.extend(_AUDIO_URL_RE.findall(node))
    elif isinstance(node, dict):
        for v in node.values():
            found.extend(_find_audio_urls(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_find_audio_urls(v))
    return found


@register
class LibraryOfCongress(SiteAdapter):
    name = "loc"
    base_url = "https://www.loc.gov/"

    def __init__(self) -> None:
        self.collection = env_str("LOC_COLLECTION", "national-jukebox")
        self.query = env_str("LOC_QUERY") or (
            f"https://www.loc.gov/collections/{self.collection}/?fo=json"
        )
        self.max_items = max(1, env_int("LOC_MAX_ITEMS", 100))
        self._items = 0

    def seeds(self) -> list[str]:
        return [_with_json(self.query)]

    def _is_item(self, url: str) -> bool:
        return "/item/" in url or "/resource/" in url

    def next_links(self, page_url: str, body: str) -> list[str]:
        if self._is_item(page_url):
            return []
        try:
            data = json.loads(body)
        except ValueError:
            return []

        links: list[str] = []
        for res in data.get("results", []) or []:
            if self._items >= self.max_items:
                break
            item_url = res.get("id") or res.get("url")
            if item_url and self._is_item(item_url):
                self._items += 1
                links.append(_with_json(item_url))

        nxt = (data.get("pagination") or {}).get("next")
        if nxt and self._items < self.max_items:
            links.append(_with_json(nxt))
        return links

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        if not self._is_item(page_url):
            return []
        try:
            data = json.loads(body)
        except ValueError:
            return []

        item = data.get("item", data) if isinstance(data, dict) else {}
        title = (item.get("title") or "Untitled").strip() if isinstance(item, dict) else "Untitled"
        rights = ""
        if isinstance(item, dict):
            rights = str(
                item.get("rights_advisory")
                or item.get("rights")
                or item.get("access_advisory")
                or ""
            ).strip()
        author = "Library of Congress"

        urls = list(dict.fromkeys(_find_audio_urls(data)))
        items: list[MediaItem] = []
        multi = len(urls) > 1
        for i, url in enumerate(urls, 1):
            ext = ext_of(url) or "mp3"
            track_title = f"{title} ({i})" if multi else title
            items.append(
                MediaItem(
                    url=url,
                    title=track_title,
                    author=author,
                    album=title if multi else "",
                    source=self.name,
                    ext=ext,
                    license=rights or "see-loc-item",
                )
            )
        return items
