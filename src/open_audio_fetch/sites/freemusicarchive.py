"""Adapter for the Free Music Archive — Creative-Commons music (best-effort).

FMA's original public API was retired after the site changed ownership, so this
adapter scrapes: it follows genre/browse pages and pulls direct audio links and
per-track download links. It captures each page's specific Creative Commons
license URL when present, because CC terms (attribution / NC / SA) vary per
track and must ride along into the manifest.

This is the most fragile adapter — FMA leans on JavaScript, so a static fetch
may surface fewer tracks than the live site shows. Treat it as best-effort and
update the selectors if the markup shifts.

Config:
  FMA_START   comma list of start paths (default: the top genres index)
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from . import MediaItem, SiteAdapter, register
from ._helpers import env_list, ext_of, strip_tags

_BASE = "https://freemusicarchive.org/"

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
# Direct audio files, or FMA's per-track download endpoints.
_AUDIO_RE = re.compile(
    r"""["'(]\s*(https?://[^"'()\s]+?(?:\.mp3|/download)[^"'()\s]*)\s*["')]""", re.I
)
_CC_RE = re.compile(r"https?://creativecommons\.org/licenses/[a-z-]+/[0-9.]+/?", re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)

_FOLLOW_HINTS = ("/genre/", "/music/", "/albums/", "/label/", "/curator/")


@register
class FreeMusicArchive(SiteAdapter):
    name = "freemusicarchive"
    base_url = _BASE

    def __init__(self) -> None:
        self.starts = env_list("FMA_START", ("genre/",))

    def seeds(self) -> list[str]:
        return [urljoin(_BASE, s) for s in self.starts]

    def next_links(self, page_url: str, html: str) -> list[str]:
        links: list[str] = []
        for href in _HREF_RE.findall(html):
            absu = urljoin(page_url, href.strip()).split("#", 1)[0]
            parts = urlsplit(absu)
            if not parts.netloc.endswith("freemusicarchive.org"):
                continue
            if any(h in parts.path for h in _FOLLOW_HINTS):
                links.append(absu)
        return links

    def extract_media(self, page_url: str, html: str) -> list[MediaItem]:
        urls = list(dict.fromkeys(_AUDIO_RE.findall(html)))
        if not urls:
            return []

        heading = ""
        m = _H1_RE.search(html) or _TITLE_RE.search(html)
        if m:
            heading = strip_tags(m.group(1))
        cc = _CC_RE.search(html)
        license_ = cc.group(0) if cc else "creative-commons"

        items: list[MediaItem] = []
        for url in urls:
            ext = ext_of(url) or "mp3"
            stem = re.sub(r"\.[^.]+$", "", url.rstrip("/").rsplit("/", 1)[-1]) or heading
            items.append(
                MediaItem(
                    url=url,
                    title=heading or stem or "Untitled",
                    author="Various",
                    source=self.name,
                    ext=ext,
                    license=license_,
                )
            )
        return items
