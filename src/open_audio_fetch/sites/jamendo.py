"""Adapter for Jamendo — 600k+ Creative-Commons music tracks, official API.

``api.jamendo.com/v3.0/tracks`` returns tracks that carry a direct
``audiodownload`` URL and a ``license_ccurl`` (the specific CC license). We only
request tracks whose download is permitted (``audiodownload_allowed=true``) and
we record each track's exact CC license so redistribution terms are never lost.

Requires a free client id (register at developer.jamendo.com):

  JAMENDO_CLIENT_ID   required — the app client id
  JAMENDO_LIMIT       tracks per page (max 200)   (default: 200)
  JAMENDO_MAX_TRACKS  cap on tracks processed     (default: 200)
  JAMENDO_TAGS        optional tag/genre filter, e.g. "classical,piano"
  JAMENDO_ORDER       API order (default: popularity_total)
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

from . import MediaItem, SiteAdapter, register
from ._helpers import env_int, env_str

_API = "https://api.jamendo.com/v3.0/tracks/"


@register
class Jamendo(SiteAdapter):
    name = "jamendo"
    base_url = "https://www.jamendo.com/"

    def __init__(self) -> None:
        self.client_id = env_str("JAMENDO_CLIENT_ID")
        self.limit = min(200, max(1, env_int("JAMENDO_LIMIT", 200)))
        self.max_tracks = max(1, env_int("JAMENDO_MAX_TRACKS", 200))
        self.tags = env_str("JAMENDO_TAGS")
        self.order = env_str("JAMENDO_ORDER", "popularity_total")
        self._tracks = 0

    def _url(self, offset: int) -> str:
        params = {
            "client_id": self.client_id,
            "format": "json",
            "limit": str(self.limit),
            "offset": str(offset),
            "audiodownload_allowed": "true",
            "include": "licenses",
            "order": self.order,
        }
        if self.tags:
            params["tags"] = self.tags
            params["fuzzytags"] = self.tags
        return f"{_API}?{urlencode(params)}"

    def seeds(self) -> list[str]:
        if not self.client_id:
            raise RuntimeError(
                "Jamendo needs a free API key: set JAMENDO_CLIENT_ID "
                "(register at https://developer.jamendo.com)."
            )
        return [self._url(0)]

    def _offset_of(self, url: str) -> int:
        for part in url.split("?", 1)[-1].split("&"):
            if part.startswith("offset="):
                try:
                    return int(part[len("offset="):])
                except ValueError:
                    return 0
        return 0

    def next_links(self, page_url: str, body: str) -> list[str]:
        try:
            results = json.loads(body).get("results", []) or []
        except ValueError:
            return []
        if len(results) >= self.limit and self._tracks < self.max_tracks:
            return [self._url(self._offset_of(page_url) + self.limit)]
        return []

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        try:
            results = json.loads(body).get("results", []) or []
        except ValueError:
            return []

        items: list[MediaItem] = []
        for t in results:
            if self._tracks >= self.max_tracks:
                break
            download = t.get("audiodownload")
            if not download or t.get("audiodownload_allowed") is False:
                continue
            self._tracks += 1
            items.append(
                MediaItem(
                    url=download,
                    title=(t.get("name") or "Untitled").strip(),
                    author=(t.get("artist_name") or "Unknown").strip(),
                    album=(t.get("album_name") or "").strip(),
                    source=self.name,
                    ext="mp3",  # Jamendo's audiodownload serves MP3
                    license=t.get("license_ccurl") or "creative-commons",
                )
            )
        return items
