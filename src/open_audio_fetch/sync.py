"""Sync-to-device mode — fill a mounted player with a mix of free audio.

"Fill my device with good-for-the-brain audio" in one command. It sizes the pull
to the device's free space, splits that budget across a category mix (default
40% audiobooks / 40% music / 20% podcasts), and runs the normal engine once per
category with a per-category `--max-bytes` slice. Everything else — politeness,
resilience, resume, integrity, dedupe — comes for free from the engine.

Each category maps to a source *recipe*. We prefer **key-free** sources so a bare
run works with no setup: audiobooks and music both come from archive.org (public
domain / Creative Commons). Podcasts need free Podcast Index credentials; if they
are absent, that category is dropped and its budget is reallocated across the
categories that *do* have a usable source (so the device still fills).
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from .cache import AvailabilityCache
from .http import PoliteClient
from .sites import available, get_adapter
from .fetcher import Fetcher

DEFAULT_MIX = {"audiobooks": 40, "music": 40, "podcasts": 20}

# category -> (source id, env overrides for the run, required env keys)
RECIPES: dict[str, tuple[str, dict[str, str], list[str]]] = {
    # Public-domain audiobooks from archive.org — key-free. PER-CHAPTER MP3s
    # (not whole-book zips): a byte budget is only checked *after* each file, so
    # chapter-sized files (~10 MB) respect the budget; a 200 MB book zip would
    # blow past a small budget by hundreds of MB.
    "audiobooks": ("librivox", {"LIBRIVOX_MODE": "chapters"}, []),
    # Creative-Commons netlabel music on the Internet Archive — key-free.
    "music": ("internetarchive",
              {"IA_COLLECTION": "netlabels", "IA_ONLY_EXTS": "mp3"}, []),
    # Podcasts need free Podcast Index credentials.
    "podcasts": ("podcastindex", {}, ["PODCASTINDEX_KEY", "PODCASTINDEX_SECRET"]),
}


# --- pure planning (unit-tested without a device) ---------------------------

def parse_mix(text: str) -> dict[str, int]:
    """Parse 'audiobooks=40,music=40,podcasts=20' into {category: percent}."""
    out: dict[str, int] = {}
    for part in text.split(","):
        key, _, val = part.partition("=")
        key = key.strip().lower()
        if not key or not val.strip().isdigit():
            raise ValueError(f"bad mix term {part!r} (use e.g. music=40)")
        out[key] = int(val)
    if not out or sum(out.values()) <= 0:
        raise ValueError("mix must have positive weights")
    unknown = set(out) - set(RECIPES)
    if unknown:
        raise ValueError(f"unknown mix categories: {', '.join(sorted(unknown))}")
    return out


def usable_categories(mix: dict[str, int], registry=None, env=None) -> list[str]:
    """Categories whose source is registered and has any required keys present."""
    reg = set(available()) if registry is None else set(registry)
    env = os.environ if env is None else env
    ok = []
    for cat in mix:
        src, _, need = RECIPES[cat]
        if src in reg and all(env.get(k) for k in need):
            ok.append(cat)
    return ok


def normalize_mix(mix: dict[str, int], usable: list[str]) -> dict[str, float]:
    """Drop unusable categories and renormalize weights to fractions summing 1."""
    kept = {c: mix[c] for c in mix if c in usable}
    total = sum(kept.values())
    if total <= 0:
        return {}
    return {c: kept[c] / total for c in kept}


def plan_budget(free: int, reserve: int, max_bytes: int | None = None) -> int:
    """Bytes we may use: free space minus a reserve, capped by max_bytes."""
    budget = max(0, free - reserve)
    if max_bytes is not None:
        budget = min(budget, max_bytes)
    return budget


def category_budgets(total: int, fractions: dict[str, float]) -> dict[str, int]:
    return {c: int(total * f) for c, f in fractions.items()}


@contextlib.contextmanager
def _env(overrides: dict[str, str]):
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _mb(n: float) -> str:
    return f"{n / 1e6:.0f} MB" if n < 1e9 else f"{n / 1e9:.2f} GB"


# --- the run ----------------------------------------------------------------

def run_sync(
    *,
    device: str,
    mix: dict[str, int] | None = None,
    reserve: int,
    max_bytes: int | None = None,
    delay: float = 1.0,
    timeout: float = 30.0,
    dry_run: bool = False,
    verbose: bool = True,
    use_cache: bool = False,
) -> int:
    dev = Path(device)
    if not dev.is_dir():
        print(f"error: device path {device!r} is not a mounted directory")
        return 2

    mix = mix or dict(DEFAULT_MIX)
    usable = usable_categories(mix)
    dropped = [c for c in mix if c not in usable]
    fractions = normalize_mix(mix, usable)
    if not fractions:
        print("error: no usable source for any requested category "
              "(podcasts need PODCASTINDEX_KEY/_SECRET; music/audiobooks are key-free)")
        return 2

    free = shutil.disk_usage(dev).free
    total = plan_budget(free, reserve, max_bytes)
    budgets = category_budgets(total, fractions)

    print(f"Sync -> {dev}", flush=True)
    print(f"  free: {_mb(free)} · reserve: {_mb(reserve)} · budget: {_mb(total)}"
          + (" · DRY-RUN (plan + sample only)" if dry_run else ""))
    if dropped:
        need = ", ".join(sorted({k for c in dropped for k in RECIPES[c][2]}))
        print(f"  dropped (no source/keys): {', '.join(dropped)}"
              + (f" — set {need} to include" if need else "")
              + " — budget reallocated")
    for c in sorted(budgets):
        print(f"  {c:<11} {int(fractions[c] * 100):>3}%  {_mb(budgets[c])}  "
              f"via {RECIPES[c][0]}")
    print(flush=True)

    if total <= 0:
        print("Nothing to do: no free space budget (raise --max-bytes or free space).")
        return 0

    client = PoliteClient(delay=delay, timeout=timeout)
    tot_downloaded = tot_bytes = tot_dupes = 0
    for cat in sorted(budgets):
        budget = budgets[cat]
        if budget <= 0:
            continue
        src, overrides, _ = RECIPES[cat]
        print(f"== {cat}: up to {_mb(budget)} from {src} ==", flush=True)
        with _env(overrides):
            adapter = get_adapter(src)
            cache = AvailabilityCache(f"sync-{cat}") if use_cache else None
            fetcher = Fetcher(
                adapter, client, out_dir=dev,
                dry_run=dry_run, verbose=verbose,
                # Dry-run caps are ignored by the engine, so bound the preview
                # crawl (a few pages — enough for two-stage APIs to sample).
                max_pages=3 if dry_run else 5000,
                max_bytes=budget, dedupe=True, cache=cache,
            )
            stats = fetcher.run()
        tot_downloaded += stats.downloaded
        tot_bytes += stats.bytes
        tot_dupes += stats.duplicates

    print()
    print(f"Done: {tot_downloaded} files, {_mb(tot_bytes)}"
          + (f", {tot_dupes} duplicates skipped" if tot_dupes else ""))
    if not dry_run and tot_downloaded:
        print(f"Eject safely before unplugging:  diskutil eject \"{dev}\"  "
              f"(macOS) — never yank a FAT32 device mid-write.")
    return 0
