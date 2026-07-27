"""Command-line interface for mp3-fetcher."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .catalog import FAIL, OK, WARN, diagnose, load_catalog, validate
from .http import PoliteClient
from .sites import available, get_adapter
from .fetcher import Fetcher, parse_size


def run_doctor(delay: float, timeout: float) -> int:
    """Live health-check every catalog source: robots posture + reachability.
    Network op (not for CI). Returns 1 if any active source is broken."""
    client = PoliteClient(delay=delay, timeout=timeout)
    sources = load_catalog()["sources"]
    print(f"Health-checking {len(sources)} sources (robots + reachability)...\n")
    worst_fail = False
    mark = {OK: "  ok ", WARN: "warn", FAIL: "FAIL"}
    for s in sources:
        url = s.get("check_url") or s["url"]
        robots_allows = client.allowed(url)
        reachable, detail = client.probe(url) if robots_allows else (False, "robots-disallow")
        level, note = diagnose(s, robots_allows, reachable)
        worst_fail = worst_fail or level == FAIL
        print(f"  [{mark[level]}] {s['id']:<18} {detail:<14} {note}")
    print()
    if worst_fail:
        print("Some ACTIVE sources are broken (see FAIL above).")
        return 1
    print("No active-source failures.")
    return 0


def print_catalog(category: str | None = None) -> None:
    catalog = load_catalog()
    sources = catalog["sources"]
    if category:
        sources = [s for s in sources if category in s["categories"]]
    impl = {s.strip() for s in available()}
    print(f"Known free-audio sources ({len(sources)}):\n")
    for s in sources:
        mark = "✓" if s["adapter_status"] == "implemented" or s["id"] in impl else " "
        cats = ", ".join(s["categories"])
        print(f"  [{mark}] {s['id']:<20} {s['license']:<16} {cats}")
        print(f"      {s['name']}  <{s['url']}>")
    print("\n  ✓ = adapter implemented.  Others are on the backlog (see backlog.md).")
    print("  Run:  open-audio-fetch <id>   to slurp an implemented source.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="open-audio-fetch",
        description="Politely download freely-offered audio into a clean folder tree.",
    )
    p.add_argument(
        "site",
        nargs="?",
        default="listentogenius",
        help=f"source to slurp (default: listentogenius). available: {', '.join(available())}",
    )
    p.add_argument(
        "-o", "--out", type=Path, default=Path("downloads"),
        help="output directory (default: ./downloads)",
    )
    p.add_argument(
        "--delay", type=float, default=1.0,
        help="minimum seconds between requests to a host (default: 1.0)",
    )
    p.add_argument(
        "--timeout", type=float, default=30.0,
        help="per-request timeout in seconds (default: 30)",
    )
    p.add_argument(
        "--max-pages", type=int, default=5000,
        help="safety cap on pages crawled (default: 5000)",
    )
    p.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="stop after downloading N files",
    )
    p.add_argument(
        "--max-bytes", type=str, default=None, metavar="SIZE",
        help="stop once SIZE has been downloaded (e.g. 500M, 2G, 750k)",
    )
    p.add_argument(
        "--cache", action="store_true",
        help="use/build a per-machine availability cache to skip re-crawling",
    )
    p.add_argument(
        "--refresh", action="store_true",
        help="with --cache, force a re-crawl and rebuild the cache",
    )
    p.add_argument(
        "--cache-ttl", type=float, default=168.0, metavar="HOURS",
        help="how long a cache entry stays fresh (default: 168h = 7 days)",
    )
    p.add_argument(
        "--dedupe", action="store_true",
        help="skip works already downloaded (by author+title, across sources/runs)",
    )
    p.add_argument(
        "--device", type=str, default=None, metavar="PATH",
        help="SYNC MODE: fill this mounted device with a mix of free audio, "
             "sized to its free space",
    )
    p.add_argument(
        "--mix", type=str, default="audiobooks=40,music=40,podcasts=20",
        help="sync mix as category=percent (default: audiobooks=40,music=40,podcasts=20)",
    )
    p.add_argument(
        "--reserve", type=str, default="200M", metavar="SIZE",
        help="free space to leave on the device in sync mode (default: 200M)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="discover and list media without downloading anything",
    )
    p.add_argument(
        "--ignore-robots", action="store_true",
        help="do NOT consult robots.txt (default: obey it)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress logs")
    p.add_argument("--list-sites", action="store_true", help="list implemented adapters and exit")
    p.add_argument(
        "--catalog", nargs="?", const="", metavar="CATEGORY",
        help="print the index of all known free-audio sources (optionally filtered "
             "by category: music, audiobooks, podcasts, classics, educational, "
             "historical) and exit",
    )
    p.add_argument(
        "--validate-catalog", action="store_true",
        help="validate catalog.json against the schema (legality gate) and exit",
    )
    p.add_argument(
        "--doctor", action="store_true",
        help="live health-check every catalog source (robots + reachability) and exit",
    )
    p.add_argument("--version", action="version", version=f"open-audio-fetch {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_sites:
        print("\n".join(available()))
        return 0

    if args.catalog is not None:
        print_catalog(args.catalog or None)
        return 0

    if args.validate_catalog:
        errors = validate()
        if errors:
            print(f"catalog INVALID — {len(errors)} error(s):", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        cat = load_catalog()
        print(f"catalog OK — {len(cat['sources'])} sources, schema v{cat['version']}")
        return 0

    if args.doctor:
        return run_doctor(args.delay, args.timeout)

    if args.device:
        from .sync import parse_mix, run_sync
        try:
            mix = parse_mix(args.mix)
            reserve = parse_size(args.reserve)
            max_bytes = parse_size(args.max_bytes) if args.max_bytes else None
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        return run_sync(
            device=args.device, mix=mix, reserve=reserve, max_bytes=max_bytes,
            delay=args.delay, timeout=args.timeout, dry_run=args.dry_run,
            verbose=not args.quiet, use_cache=args.cache,
        )

    try:
        adapter = get_adapter(args.site)
    except KeyError as err:
        print(err, file=sys.stderr)
        return 2

    # Let quota-aware adapters (e.g. Musopen) avoid burning real quota while
    # only discovering.
    if args.dry_run:
        os.environ["OPEN_AUDIO_FETCH_DRY_RUN"] = "1"

    try:
        max_bytes = parse_size(args.max_bytes) if args.max_bytes else None
    except ValueError:
        print(f"error: invalid --max-bytes value {args.max_bytes!r}", file=sys.stderr)
        return 2

    cache = None
    if args.cache:
        from .cache import AvailabilityCache
        cache = AvailabilityCache(args.site)

    client = PoliteClient(
        delay=args.delay,
        timeout=args.timeout,
        obey_robots=not args.ignore_robots,
    )
    fetcher = Fetcher(
        adapter,
        client,
        out_dir=args.out,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
        verbose=not args.quiet,
        limit=args.limit,
        max_bytes=max_bytes,
        cache=cache,
        refresh=args.refresh,
        cache_ttl=args.cache_ttl * 3600,
        dedupe=args.dedupe,
    )
    try:
        stats = fetcher.run()
    except RuntimeError as err:
        # Adapters raise this for missing configuration (e.g. an API key).
        print(f"error: {err}", file=sys.stderr)
        return 2
    # Non-zero exit if we found media but every attempt failed.
    if stats.media_found and stats.downloaded == 0 and not args.dry_run:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
