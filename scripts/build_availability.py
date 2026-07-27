#!/usr/bin/env python3
"""Build the repo availability index — the "flag files" of what can be downloaded.

A scheduled bot runs this and commits the result. Each source gets its own shard
at `availability/<source>.json` (never one big file) so concurrent regenerations
of different sources never conflict, and each shard is written deterministically
(sorted) so diffs are minimal.

The index is a NON-AUTHORITATIVE hint: the downloader re-confirms every file at
fetch time, so a stale entry costs at most one failed fetch. It exists so a fresh
clone can warm-start (see `--cache`) instead of crawling cold.

Usage (network op; not for CI):
    python3 scripts/build_availability.py --all
    python3 scripts/build_availability.py librivox internetarchive
    python3 scripts/build_availability.py librivox --max-pages 20 --delay 1

Only sources with a registered adapter and robots_ok=true are built; others are
skipped with a note.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_audio_fetch.cache import AvailabilityCache  # noqa: E402
from open_audio_fetch.catalog import load_catalog  # noqa: E402
from open_audio_fetch.http import PoliteClient  # noqa: E402
from open_audio_fetch.sites import available, get_adapter  # noqa: E402
from open_audio_fetch.fetcher import discover  # noqa: E402

INDEX_DIR = ROOT / "availability"


def buildable(catalog: dict) -> dict[str, dict]:
    reg = set(available())
    return {
        s["id"]: s
        for s in catalog["sources"]
        if s["id"] in reg and s.get("robots_ok")
        and s.get("adapter_status") in ("implemented", "experimental")
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", nargs="*", help="source ids to build (default: --all)")
    p.add_argument("--all", action="store_true", help="build every buildable source")
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--delay", type=float, default=1.0)
    args = p.parse_args(argv)

    catalog = load_catalog()
    candidates = buildable(catalog)
    if args.all or not args.sources:
        targets = sorted(candidates)
    else:
        targets = args.sources

    client = PoliteClient(delay=args.delay)
    built = 0
    for sid in targets:
        if sid not in candidates:
            print(f"[skip] {sid}: not buildable (no adapter or robots_ok=false)")
            continue
        try:
            items = discover(get_adapter(sid), client, max_pages=args.max_pages)
        except Exception as err:  # noqa: BLE001
            print(f"[fail] {sid}: {type(err).__name__}: {err}")
            continue
        if not items:
            print(f"[skip] {sid}: 0 items discovered (nothing to publish)")
            continue
        AvailabilityCache(sid, base_dir=INDEX_DIR).save(items)
        print(f"[ok]   {sid}: {len(items)} items -> availability/{sid}.json")
        built += 1

    print(f"\nbuilt {built} shard(s) in {INDEX_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
