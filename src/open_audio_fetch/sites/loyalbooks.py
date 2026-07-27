"""Adapter for Loyal Books (loyalbooks.com) — public-domain audiobooks.

Loyal Books is largely a friendlier front-end over LibriVox's public-domain
catalog. We crawl its genre and book pages and grab the per-chapter MP3s (and
whole-book zips when linked), filing chapters under the book as an album.

Because the same recordings also live on LibriVox and the Internet Archive, the
cross-source dedupe backlog item will later reconcile these by author+title;
for now each source keeps its own tree.

Config:
  LOYALBOOKS_START  comma list of start paths (default: the homepage, which
                    links out to ~80 book pages; follow those + genre pages)
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from . import MediaItem, SiteAdapter, register
from ._helpers import env_list, ext_of, strip_tags

_BASE = "https://www.loyalbooks.com/"

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_MEDIA_RE = re.compile(
    r"""["'(]\s*([^"'()\s]+?\.(?:mp3|zip))\s*["')]""", re.I
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)

_FOLLOW_HINTS = ("/genre/", "/book/", "/Children", "/Fiction", "/collection")


@register
class LoyalBooks(SiteAdapter):
    name = "loyalbooks"
    base_url = _BASE

    def __init__(self) -> None:
        # The homepage links to ~80 books; the crawler follows /book/ and
        # /genre/ from there. (Empty path -> the homepage itself.)
        self.starts = env_list("LOYALBOOKS_START", ("",))

    def seeds(self) -> list[str]:
        return [urljoin(_BASE, s) for s in self.starts]

    def next_links(self, page_url: str, html: str) -> list[str]:
        links: list[str] = []
        for href in _HREF_RE.findall(html):
            absu = urljoin(page_url, href.strip()).split("#", 1)[0]
            parts = urlsplit(absu)
            if not parts.netloc.endswith("loyalbooks.com"):
                continue
            if parts.path.lower().endswith((".mp3", ".zip")):
                continue
            if any(h in absu for h in _FOLLOW_HINTS):
                links.append(absu)
        return links

    def extract_media(self, page_url: str, html: str) -> list[MediaItem]:
        paths = list(dict.fromkeys(_MEDIA_RE.findall(html)))
        if not paths:
            return []

        heading = ""
        m = _H1_RE.search(html) or _TITLE_RE.search(html)
        if m:
            heading = strip_tags(m.group(1))
        album = heading.split("|")[0].strip() if heading else ""

        items: list[MediaItem] = []
        for path in paths:
            url = urljoin(page_url, path)
            ext = ext_of(path) or "mp3"
            stem = re.sub(r"\.[^.]+$", "", path.rsplit("/", 1)[-1])
            # A whole-book zip is titled by the book; chapters by their file.
            title = album if ext == "zip" and album else (stem or album or "Untitled")
            items.append(
                MediaItem(
                    url=url,
                    title=title,
                    author="Various",
                    album=album if ext != "zip" else "",
                    source=self.name,
                    ext=ext,
                    license="public-domain",
                )
            )
        return items
