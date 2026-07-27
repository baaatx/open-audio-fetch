"""Adapter for the Internet Archive — the mega-source.

Uses the public JSON APIs rather than scraping:

  1. ``advancedsearch.php`` returns item *identifiers* for a query, paged.
  2. ``/metadata/<identifier>`` lists every file in an item.
  3. ``/download/<identifier>/<file>`` serves the actual audio.

The crawl model maps cleanly onto this: ``seeds()`` issues the first search
page; ``next_links()`` turns a search response into ``/metadata`` URLs (and the
next search page); ``extract_media()`` turns a metadata response into download
MediaItems. Because a single item ships the same track in several formats
(FLAC original + MP3/OGG derivatives), we keep only the best-ranked format per
track so we don't store three copies of everything.

Config via environment (sane defaults so a bare ``--dry-run`` works):

  IA_COLLECTION   collection to pull      (default: librivoxaudio)
  IA_QUERY        raw Lucene query, overrides IA_COLLECTION
  IA_ROWS         search page size        (default: 50)
  IA_MAX_ITEMS    cap on items processed  (default: 100)
  IA_FORMATS      comma list, format preference (default: mp3,ogg,flac,…)
  IA_ONLY_EXTS    comma list; if set, keep ONLY these extensions. Handy when an
                  item ships the same content twice (e.g. per-chapter MP3s *and*
                  a whole-book M4B) — set "mp3" to avoid grabbing both.
  IA_PREFER       when an item has both per-chapter files and a whole-book bundle
                  (M4B / "complete" / "partN"), keep one: chapters (default) |
                  bundle | both.

License is *mixed* on IA, so we record each item's ``licenseurl``/``rights``
verbatim; the librivoxaudio collection is public domain.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

from . import MediaItem, SiteAdapter, register
from ._helpers import (
    FORMAT_PREFERENCE,
    env_int,
    env_list,
    env_str,
    ext_of,
    is_audio,
    pick_best_by_format,
)

_SEARCH = "https://archive.org/advancedsearch.php"
_METADATA = "https://archive.org/metadata/"
_DOWNLOAD = "https://archive.org/download/"


def _norm_stem(name: str) -> str:
    """Collapse a filename to a track key shared by its format variants.

    ``Track01.flac`` / ``Track01.mp3`` / ``Track01_64kb.mp3`` all key to the
    same track so we pick one download, not three.
    """
    base = name.rsplit("/", 1)[-1]
    ext = ext_of(base)
    if ext:
        base = base[: -(len(ext) + 1)]
    base = base.lower()
    for marker in ("_64kb", "_128kbps", "_128kb", "_vbr", "_spoken", "_64"):
        if base.endswith(marker):
            base = base[: -len(marker)]
    return base.strip("._ ") or name.lower()


def _as_text(value) -> str:
    """IA metadata fields are sometimes a string, sometimes a list."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value else ""


# Whole-book "bundle" packaging: the M4B audiobook container, or a file whose
# name marks it as the complete work / a multi-part split of it.
_BUNDLE_MARK = re.compile(r"(_complete|_full|_whole|_entire|part[\s_]*\d)", re.I)


def _is_bundle(fname: str, ext: str) -> bool:
    return ext == "m4b" or bool(_BUNDLE_MARK.search(fname.rsplit("/", 1)[-1]))


@register
class InternetArchive(SiteAdapter):
    name = "internetarchive"
    base_url = "https://archive.org/"

    def __init__(self) -> None:
        self.collection = env_str("IA_COLLECTION", "librivoxaudio")
        self.query = env_str("IA_QUERY") or (
            f"collection:{self.collection} AND mediatype:audio"
        )
        self.rows = max(1, env_int("IA_ROWS", 50))
        self.max_items = max(1, env_int("IA_MAX_ITEMS", 100))
        self.preference = env_list("IA_FORMATS", FORMAT_PREFERENCE)
        self.only_exts = {e.lower() for e in env_list("IA_ONLY_EXTS")}
        # When an item ships BOTH per-chapter files and a whole-book bundle,
        # keep just one packaging. chapters (default) | bundle | both.
        self.prefer = env_str("IA_PREFER", "chapters").lower()
        self._emitted = 0  # how many /metadata URLs we have handed out

    # -- URL helpers ---------------------------------------------------------

    def _search_url(self, page: int) -> str:
        params = [
            ("q", self.query),
            ("fl[]", "identifier"),
            ("sort[]", "identifier asc"),
            ("rows", str(self.rows)),
            ("page", str(page)),
            ("output", "json"),
        ]
        return f"{_SEARCH}?{urlencode(params)}"

    def seeds(self) -> list[str]:
        return [self._search_url(1)]

    # -- crawl ---------------------------------------------------------------

    def next_links(self, page_url: str, body: str) -> list[str]:
        if "/metadata/" in page_url:
            return []  # metadata pages are leaves
        if "advancedsearch.php" not in page_url:
            return []
        try:
            data = json.loads(body)
        except ValueError:
            return []

        resp = data.get("response", {})
        docs = resp.get("docs", []) or []
        num_found = int(resp.get("numFound", 0) or 0)
        # Where are we in the paging? advancedsearch echoes the request params.
        page = int(resp.get("start", 0) // self.rows) + 1 if resp.get("start") else 1
        header = data.get("responseHeader", {}).get("params", {})
        if "page" in header:
            try:
                page = int(header["page"])
            except (TypeError, ValueError):
                pass

        links: list[str] = []
        for doc in docs:
            ident = doc.get("identifier")
            if not ident:
                continue
            if self._emitted >= self.max_items:
                break
            self._emitted += 1
            links.append(f"{_METADATA}{quote(ident, safe='')}")

        # Queue the next search page only while we still have budget for items.
        if self._emitted < self.max_items and page * self.rows < num_found:
            links.append(self._search_url(page + 1))
        return links

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        if "/metadata/" not in page_url:
            return []
        try:
            data = json.loads(body)
        except ValueError:
            return []

        meta = data.get("metadata", {}) or {}
        files = data.get("files", []) or []
        identifier = meta.get("identifier") or page_url.rsplit("/", 1)[-1]
        author = _as_text(meta.get("creator")) or "Unknown"
        album = _as_text(meta.get("title")) or identifier
        license_ = (
            _as_text(meta.get("licenseurl"))
            or _as_text(meta.get("rights"))
            or _as_text(meta.get("possible-copyright-status"))
        )
        if not license_:
            collections = _as_text(meta.get("collection")).lower()
            license_ = "public-domain" if "librivox" in collections else "mixed/see-item"

        # Group format variants of each track, keep the best one.
        by_track: dict[str, list[tuple[str, dict]]] = {}
        order: list[str] = []
        for f in files:
            fname = f.get("name", "")
            if not fname or not is_audio(fname):
                continue
            if self.only_exts and ext_of(fname) not in self.only_exts:
                continue
            key = _norm_stem(fname)
            if key not in by_track:
                by_track[key] = []
                order.append(key)
            by_track[key].append((ext_of(fname), f))

        built: list[tuple[MediaItem, bool]] = []  # (item, is_bundle)
        for key in order:
            variants = by_track[key]
            best = pick_best_by_format(
                [(ext, (ext, f)) for ext, f in variants], self.preference
            )
            if best is None:
                continue
            ext, f = best[1]
            fname = f["name"]
            track = f.get("track", "")
            fudge = str(track).split("/")[0].strip() if track else ""
            base_title = f.get("title") or _norm_stem(fname)
            title = f"{int(fudge):02d} {base_title}" if fudge.isdigit() else base_title
            url = f"{_DOWNLOAD}{quote(identifier, safe='')}/{quote(fname, safe='/')}"
            built.append((
                MediaItem(
                    url=url,
                    title=title,
                    author=author,
                    album=album,
                    source=self.name,
                    ext=ext or "mp3",
                    license=license_,
                ),
                _is_bundle(fname, ext),
            ))

        # Cross-packaging dedupe: if this item ships BOTH per-chapter files and a
        # whole-book bundle (e.g. LibriVox's M4B alongside chapter MP3s), keep
        # only the preferred packaging so the same audio isn't downloaded twice.
        chapters = [it for it, bundle in built if not bundle]
        bundles = [it for it, bundle in built if bundle]
        if self.prefer in ("chapters", "bundle") and chapters and bundles:
            return chapters if self.prefer == "chapters" else bundles
        return [it for it, _ in built]
