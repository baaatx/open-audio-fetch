"""Adapter for LibriVox — public-domain audiobooks, via the official API.

``/api/feed/audiobooks/?format=json&extended=1`` returns whole books, each
carrying both a ``url_zip_file`` (the entire book as one MP3 zip) and, with
``extended=1``, a ``sections`` list of per-chapter ``listen_url`` MP3s. That
single feed is all we need — pagination walks it with ``offset``.

Everything on LibriVox is public domain, so the license is fixed.

Two modes (env ``LIBRIVOX_MODE``):
  * ``zip``      one download per book — the whole-book MP3 zip  (default)
  * ``chapters`` one download per chapter — filed under the book as an album

Config:
  LIBRIVOX_MODE       zip | chapters          (default: zip)
  LIBRIVOX_LIMIT      books per feed page     (default: 50)
  LIBRIVOX_MAX_BOOKS  cap on books processed  (default: 50)
"""

from __future__ import annotations

import json

from . import MediaItem, SiteAdapter, register
from ._helpers import env_int, env_str, ext_of

_FEED = "https://librivox.org/api/feed/audiobooks/"


def _author(book: dict) -> str:
    authors = book.get("authors") or []
    names = []
    for a in authors:
        full = f"{a.get('first_name', '').strip()} {a.get('last_name', '').strip()}".strip()
        if full and full.lower() not in ("various", ""):
            names.append(full)
    if not names:
        return "Various"
    return names[0] if len(names) == 1 else f"{names[0]} et al."


@register
class LibriVox(SiteAdapter):
    name = "librivox"
    base_url = "https://librivox.org/"

    def __init__(self) -> None:
        self.mode = env_str("LIBRIVOX_MODE", "zip").lower()
        if self.mode not in ("zip", "chapters"):
            self.mode = "zip"
        self.limit = max(1, env_int("LIBRIVOX_LIMIT", 50))
        self.max_books = max(1, env_int("LIBRIVOX_MAX_BOOKS", 50))
        self._books = 0

    def _feed_url(self, offset: int) -> str:
        return f"{_FEED}?format=json&extended=1&limit={self.limit}&offset={offset}"

    def seeds(self) -> list[str]:
        return [self._feed_url(0)]

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
            books = json.loads(body).get("books", []) or []
        except ValueError:
            return []
        # A full page implies more may follow; stop once we hit the cap.
        if len(books) >= self.limit and self._books < self.max_books:
            return [self._feed_url(self._offset_of(page_url) + self.limit)]
        return []

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        try:
            books = json.loads(body).get("books", []) or []
        except ValueError:
            return []

        items: list[MediaItem] = []
        for book in books:
            if self._books >= self.max_books:
                break
            self._books += 1
            title = (book.get("title") or "Untitled").strip()
            author = _author(book)

            if self.mode == "zip":
                zip_url = book.get("url_zip_file")
                if zip_url:
                    items.append(
                        MediaItem(
                            url=zip_url,
                            title=title,
                            author=author,
                            source=self.name,
                            ext=ext_of(zip_url) or "zip",
                            license="public-domain",
                        )
                    )
                continue

            # chapters mode
            for sec in book.get("sections") or []:
                listen = sec.get("listen_url")
                if not listen:
                    continue
                num = str(sec.get("section_number") or "").strip()
                sec_title = (sec.get("title") or f"Section {num}").strip()
                label = f"{int(num):02d} {sec_title}" if num.isdigit() else sec_title
                items.append(
                    MediaItem(
                        url=listen,
                        title=label,
                        author=author,
                        album=title,
                        source=self.name,
                        ext=ext_of(listen) or "mp3",
                        license="public-domain",
                    )
                )
        return items
