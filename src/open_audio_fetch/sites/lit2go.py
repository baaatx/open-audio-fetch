"""Adapter for Lit2Go (etc.usf.edu/lit2go) — public-domain educational audio.

Lit2Go publishes classic literature as free MP3s with reading levels and
companion texts, all public domain. Rather than hard-code its exact markup we
crawl defensively: follow internal ``/lit2go/`` listing and book pages, and
grab any ``.mp3`` link we find, naming each file from the book/page heading.

The audio files live on a media host; we file them under the book as an album.

Config:
  LIT2GO_PDF   set to 1 to also fetch companion PDFs alongside audio (default: off)
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from . import MediaItem, SiteAdapter, register
from ._helpers import env_str, ext_of, strip_tags

_BASE = "https://etc.usf.edu/lit2go/"

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_MEDIA_RE = re.compile(r"""["'(]\s*([^"'()\s]+?\.(?:mp3|pdf))\s*["')]""", re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


@register
class Lit2Go(SiteAdapter):
    name = "lit2go"
    base_url = _BASE

    def __init__(self) -> None:
        self.want_pdf = env_str("LIT2GO_PDF") in ("1", "true", "yes", "on")

    def seeds(self) -> list[str]:
        # The books, authors and genres indexes together reach every work.
        return [
            urljoin(_BASE, "books/"),
            urljoin(_BASE, "authors/"),
            urljoin(_BASE, "genres/"),
        ]

    def next_links(self, page_url: str, html: str) -> list[str]:
        links: list[str] = []
        for href in _HREF_RE.findall(html):
            absu = urljoin(page_url, href.strip())
            parts = urlsplit(absu)
            if parts.netloc.endswith("usf.edu") and "/lit2go/" in parts.path:
                # Skip direct media; those are handled by extract_media.
                if not parts.path.lower().endswith((".mp3", ".pdf")):
                    links.append(absu.split("#", 1)[0])
        return links

    def extract_media(self, page_url: str, html: str) -> list[MediaItem]:
        paths = list(dict.fromkeys(_MEDIA_RE.findall(html)))
        if not paths:
            return []

        # The <title> carries everything (the <h1> is just the site logo):
        #   "Chapter I: ... | Book Title | Author | Lit2Go ETC"
        chapter = book = ""
        author = "Various"
        m = _TITLE_RE.search(html)
        if m:
            parts = [p.strip() for p in strip_tags(m.group(1)).split("|")]
            parts = [p for p in parts if p and not p.lower().startswith("lit2go")]
            if parts:
                chapter = parts[0]
            if len(parts) >= 2:
                book = parts[1]
            if len(parts) >= 3:
                author = parts[2]

        # Only the files we'll actually emit (a chapter page also links a PDF).
        emit = [p for p in paths if not (ext_of(p) == "pdf" and not self.want_pdf)]
        multi = len(emit) > 1

        items: list[MediaItem] = []
        for path in emit:
            ext = ext_of(path)
            url = urljoin(page_url, path)
            stem = re.sub(r"\.[^.]+$", "", path.rsplit("/", 1)[-1])
            # Keep titles unique only when a page really exposes several files.
            title = f"{chapter} ({stem})" if (chapter and multi) else (chapter or stem)
            items.append(
                MediaItem(
                    url=url,
                    title=title,
                    author=author,
                    album=book,
                    source=self.name,
                    ext=ext or "mp3",
                    license="public-domain",
                )
            )
        return items
