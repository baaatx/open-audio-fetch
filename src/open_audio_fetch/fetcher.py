"""The crawl-and-download engine.

Breadth-first over a site's pages (bounded and paced), collecting MediaItems
and streaming each new one to a clean `<out>/<source>/<Author>/<Title>.mp3`
layout. Already-downloaded files are skipped so runs are resumable, and every
download is appended to a CSV manifest.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .http import PoliteClient
from .sites import MediaItem, SiteAdapter

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def discover(adapter, client, *, max_pages: int = 200) -> list:
    """Enumerate a source's available MediaItems WITHOUT downloading anything.

    A pure discovery crawl (seeds -> next_links -> extract_media), used to build
    the availability index. Deduplicates by URL; bounded by max_pages."""
    from collections import deque

    queue: deque = deque(adapter.seeds())
    seen_pages = set(queue)
    seen_media: set[str] = set()
    out: list = []
    pages = 0
    while queue and pages < max_pages:
        url = queue.popleft()
        try:
            body = client.get_text(url, headers=adapter.headers_for(url))
        except Exception:
            continue
        pages += 1
        for item in adapter.extract_media(url, body):
            if item.url in seen_media:
                continue
            seen_media.add(item.url)
            out.append(item)
        for link in adapter.next_links(url, body):
            if link not in seen_pages:
                seen_pages.add(link)
                queue.append(link)
    return out


def parse_size(text: str) -> int:
    """Parse a human byte size like '500M', '2G', '750k', or a plain int.

    Binary units (1K = 1024). Raises ValueError on garbage."""
    s = str(text).strip().upper().rstrip("B")
    mult = 1
    if s and s[-1] in "KMGT":
        mult = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[s[-1]]
        s = s[:-1].strip()
    value = float(s)
    if value < 0:
        raise ValueError("size must be non-negative")
    return int(value * mult)


def sanitize(name: str, *, fallback: str = "untitled", maxlen: int = 150) -> str:
    """Turn an arbitrary label into a safe, tidy path component."""
    name = _UNSAFE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    return name or fallback


@dataclass
class Stats:
    pages_crawled: int = 0
    media_found: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    duplicates: int = 0
    bytes: int = 0


def dedupe_key(author: str, title: str) -> str:
    """Normalized (author, title) key for cross-source duplicate detection.

    Best-effort: lowercased, whitespace-collapsed, punctuation dropped — so the
    same work grabbed from two sources with slightly different formatting still
    collides. It's a heuristic, not a fingerprint."""
    def norm(s: str) -> str:
        s = re.sub(r"[^\w\s]", "", str(s).lower())
        return re.sub(r"\s+", " ", s).strip()
    return f"{norm(author)}|{norm(title)}"


class Fetcher:
    def __init__(
        self,
        adapter: SiteAdapter,
        client: PoliteClient,
        out_dir: Path,
        *,
        max_pages: int = 5000,
        dry_run: bool = False,
        verbose: bool = True,
        limit: int | None = None,
        max_bytes: int | None = None,
        cache=None,
        refresh: bool = False,
        cache_ttl: float = 7 * 24 * 3600,
        dedupe: bool = False,
    ) -> None:
        self.adapter = adapter
        self.client = client
        self.out_dir = Path(out_dir)
        self.max_pages = max_pages
        self.dry_run = dry_run
        self.verbose = verbose
        self.limit = limit          # stop after this many downloads
        self.max_bytes = max_bytes  # stop once this many bytes are downloaded
        self.cache = cache          # AvailabilityCache | None (warm-start)
        self.refresh = refresh      # force re-crawl even if cache is fresh
        self.cache_ttl = cache_ttl
        self.dedupe = dedupe        # skip works already downloaded (any source)
        self.stats = Stats()
        self._failed: list[MediaItem] = []  # items to re-attempt at end of run
        self._seen_keys: set[str] = set()   # dedupe keys seen this run + prior

    def _cap_reached(self) -> bool:
        """True once a --limit or --max-bytes budget is spent (real runs only)."""
        if self.dry_run:
            return False
        if self.limit is not None and self.stats.downloaded >= self.limit:
            return True
        if self.max_bytes is not None and self.stats.bytes >= self.max_bytes:
            return True
        return False

    # -- helpers --------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    def _dest_for(self, item: MediaItem) -> Path:
        ext = (item.ext or "mp3").lstrip(".")
        path = (
            self.out_dir
            / sanitize(item.source or self.adapter.name, fallback="source")
            / sanitize(item.author, fallback="Unknown")
        )
        if item.album:
            path = path / sanitize(item.album, fallback="album")
        return path / f"{sanitize(item.title)}.{sanitize(ext, fallback='bin', maxlen=12)}"

    def _manifest_path(self) -> Path:
        return self.out_dir / "manifest.csv"

    def _record(self, item: MediaItem, dest: Path, status: str, size: int) -> None:
        path = self._manifest_path()
        new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(
                    ["source", "author", "album", "title", "url", "dest",
                     "license", "status", "bytes"]
                )
            w.writerow(
                [
                    item.source,
                    item.author,
                    item.album,
                    item.title,
                    item.url,
                    str(dest.relative_to(self.out_dir)),
                    item.license,
                    status,
                    size,
                ]
            )

    # -- main loop ------------------------------------------------------------

    def _load_prior_keys(self) -> None:
        """Seed dedupe keys from an existing manifest so it works across runs."""
        path = self._manifest_path()
        if not path.exists():
            return
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("status") == "downloaded":
                        self._seen_keys.add(dedupe_key(row.get("author", ""),
                                                        row.get("title", "")))
        except OSError:
            pass

    def run(self) -> Stats:
        if self.dedupe:
            self._load_prior_keys()
        # Warm start: replay a fresh availability cache instead of crawling.
        if (
            self.cache is not None
            and not self.refresh
            and self.cache.fresh(self.cache_ttl)
        ):
            cached = self.cache.load()
            if cached is not None:
                self._log(
                    f"[cache] {len(cached)} items from {self.cache.path.name} "
                    f"(use --refresh to re-crawl)"
                )
                self._consume(cached)
                return self._finish()

        discovered = self._crawl()
        if self.cache is not None and not self.dry_run:
            self.cache.save(discovered)
            self._log(f"[cache] saved {len(discovered)} items to {self.cache.path.name}")
        return self._finish()

    def _consume(self, items: list[MediaItem]) -> None:
        """Download a known list of items (the cache warm-path)."""
        seen: set[str] = set()
        for item in items:
            if item.url in seen or self._cap_reached():
                continue
            seen.add(item.url)
            self.stats.media_found += 1
            self._handle_media(item)

    def _crawl(self) -> list[MediaItem]:
        """BFS the source, downloading as we go; return everything discovered."""
        queue: deque[str] = deque(self.adapter.seeds())
        seen_pages: set[str] = set(queue)
        seen_media: set[str] = set()
        discovered: list[MediaItem] = []

        while queue and self.stats.pages_crawled < self.max_pages:
            if self._cap_reached():
                self._log("[cap] download budget reached; stopping crawl")
                break
            url = queue.popleft()
            try:
                html = self.client.get_text(url, headers=self.adapter.headers_for(url))
            except PermissionError as err:
                self._log(f"[robots] skip {url}: {err}")
                continue
            except Exception as err:
                self._log(f"[warn] failed page {url}: {err}")
                continue

            self.stats.pages_crawled += 1

            for item in self.adapter.extract_media(url, html):
                if item.url in seen_media:
                    continue
                seen_media.add(item.url)
                discovered.append(item)
                self.stats.media_found += 1
                self._handle_media(item)
                if self._cap_reached():
                    break

            for link in self.adapter.next_links(url, html):
                if link not in seen_pages:
                    seen_pages.add(link)
                    queue.append(link)

            if self.stats.pages_crawled % 25 == 0:
                self._log(
                    f"[progress] pages={self.stats.pages_crawled} "
                    f"queue={len(queue)} downloaded={self.stats.downloaded} "
                    f"skipped={self.stats.skipped}"
                )
        return discovered

    def _finish(self) -> Stats:
        # A crawl-wide safety net: anything that still failed (after the HTTP
        # client already waited out any outage) gets one more pass. Individual
        # network blips during a long pull thus don't leave gaps behind.
        if self._failed and not self.dry_run:
            self._retry_failed()

        dup = f" dup={self.stats.duplicates}" if self.stats.duplicates else ""
        self._log(
            "[done] "
            f"pages={self.stats.pages_crawled} found={self.stats.media_found} "
            f"downloaded={self.stats.downloaded} skipped={self.stats.skipped} "
            f"failed={self.stats.failed}{dup} "
            f"MB={self.stats.bytes / 1e6:.1f}"
        )
        return self.stats

    def _retry_failed(self) -> None:
        pending, self._failed = self._failed, []
        self._log(f"[retry] re-attempting {len(pending)} failed item(s)")
        for item in pending:
            dest = self._dest_for(item)
            if dest.exists() and dest.stat().st_size > 0:
                continue  # recovered by an earlier attempt already
            self.stats.failed -= 1  # _attempt_download re-adds it if it fails again
            if self._attempt_download(item, dest):
                self._log(f"[recovered] {dest.relative_to(self.out_dir)}")

    def _handle_media(self, item: MediaItem) -> None:
        dest = self._dest_for(item)
        if dest.exists() and dest.stat().st_size > 0:
            self.stats.skipped += 1
            self._log(f"[skip] {dest.relative_to(self.out_dir)} (exists)")
            if self.dedupe:
                self._seen_keys.add(dedupe_key(item.author, item.title))
            return

        if self.dedupe:
            key = dedupe_key(item.author, item.title)
            if key in self._seen_keys:
                self.stats.duplicates += 1
                self._log(f"[dup] {item.author} — {item.title} (already have it)")
                self._record(item, dest, "duplicate", 0)
                return

        if self.dry_run:
            self._log(f"[dry-run] would download {item.url} -> "
                      f"{dest.relative_to(self.out_dir)}")
            self._record(item, dest, "dry-run", 0)
            return

        if self._attempt_download(item, dest) and self.dedupe:
            self._seen_keys.add(dedupe_key(item.author, item.title))

    def _attempt_download(self, item: MediaItem, dest: Path) -> bool:
        """Try one download; update stats/manifest; queue for retry on failure."""
        try:
            size = self.client.download(
                item.url, dest, headers=self.adapter.headers_for(item.url)
            )
        except Exception as err:
            self.stats.failed += 1
            self._failed.append(item)
            self._log(f"[fail] {item.url}: {err}")
            self._record(item, dest, f"error: {err}", 0)
            return False

        self.stats.downloaded += 1
        self.stats.bytes += size
        self._log(
            f"[get] {dest.relative_to(self.out_dir)} ({size / 1e6:.1f} MB)"
        )
        self._record(item, dest, "downloaded", size)
        return True
