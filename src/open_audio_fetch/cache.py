"""Per-machine availability cache — a warm-start shortcut, never a source of truth.

Discovering what a source offers means crawling its listing/API pages, which is
the slow part of a run. This caches the discovered `MediaItem`s per source so a
repeat run can skip straight to downloading. It is deliberately:

  * **opt-in** (`--cache`) so default runs stay deterministic;
  * **degrade-safe** — a missing/stale/corrupt cache just means "go crawl";
  * **per-source sharded** JSON under `~/.cache/open-audio-fetch/availability/`,
    written deterministically (sorted keys) so it mirrors the repo-side index
    convention and diffs cleanly if ever committed.

The cache records *availability*, not truth: the downloader still confirms each
file at fetch time (skip-if-exists, integrity check), so a wrong/stale entry
costs at most one failed fetch, never a bad file.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

from .sites import MediaItem

_DEFAULT_DIR = Path("~/.cache/open-audio-fetch/availability").expanduser()
# The committed repo index (when running from a clone) — a warm-start fallback
# for a machine that has never crawled a source itself.
_REPO_INDEX_DIR = Path(__file__).resolve().parents[2] / "availability"
_FIELDS = {f.name for f in dataclasses.fields(MediaItem)}


class AvailabilityCache:
    def __init__(
        self, source: str, base_dir: Path | None = None, fallback_dir: Path | None = None
    ) -> None:
        self.source = source
        self.base_dir = Path(base_dir) if base_dir else _DEFAULT_DIR
        self.path = self.base_dir / f"{source}.json"
        # Fall back to the committed repo shard if the local cache is absent.
        fb = fallback_dir if fallback_dir is not None else _REPO_INDEX_DIR
        self.fallback = Path(fb) / f"{source}.json"

    # -- read ----------------------------------------------------------------

    def _read(self) -> dict | None:
        for path in (self.path, self.fallback):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return None

    def fresh(self, ttl_seconds: float, now: float | None = None) -> bool:
        data = self._read()
        if not data or "generated_at" not in data:
            return False
        now = time.time() if now is None else now
        return (now - float(data["generated_at"])) < ttl_seconds

    def load(self) -> list[MediaItem] | None:
        """Reconstruct the cached MediaItems, or None if unusable."""
        data = self._read()
        if not data or "items" not in data:
            return None
        items: list[MediaItem] = []
        for raw in data["items"]:
            fields = {k: v for k, v in raw.items() if k in _FIELDS}
            if "url" in fields and "title" in fields:
                items.append(MediaItem(**fields))
        return items

    # -- write ---------------------------------------------------------------

    def save(self, items: list[MediaItem], now: float | None = None) -> None:
        now = time.time() if now is None else now
        payload = {
            "source": self.source,
            "generated_at": now,
            "count": len(items),
            # Deterministic: stable field order, sorted by URL, so the file is
            # diff-friendly (mirrors the repo availability-index convention).
            "items": sorted(
                (dataclasses.asdict(i) for i in items),
                key=lambda d: d.get("url", ""),
            ),
        }
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # cache is best-effort; never break a run over it
