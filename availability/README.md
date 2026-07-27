# Availability index (`availability/`)

Machine-generated **"flag files" of what can be downloaded** per source — a
warm-start shortcut so a fresh clone doesn't have to crawl cold.

## What this is (and isn't)

- **A hint, not the truth.** The downloader re-confirms every file at fetch time
  (robots, skip-if-exists, `Content-Length` integrity), so a stale or wrong
  entry costs at most one failed fetch — never a bad file. Accuracy here is
  best-effort by design.
- **One shard per source** (`<source>.json`) — never one big file — so
  regenerating one source never conflicts with another.
- **Deterministic** (sorted keys, items sorted by URL) so diffs stay minimal and
  merges are clean as availability drifts.

## How it's built

A scheduled bot runs the builder and commits the result:

```bash
python3 scripts/build_availability.py --all        # every buildable source
python3 scripts/build_availability.py librivox     # just one
```

Only sources with a registered adapter and `robots_ok: true` are built. Each
shard records `generated_at`, a `count`, and the discovered `items`
(url/title/author/album/ext/license) — the same schema the local `--cache`
uses, so `--cache` can warm-start from these committed shards.

## Git-conflict convention

Because a bot and humans may both touch these, and availability changes over
time: shard-per-source + deterministic serialization means **last-writer-wins
per shard** is safe and merges are trivial. Don't hand-edit these files — run
the builder.
