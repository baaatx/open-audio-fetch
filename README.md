# open-audio-fetch

**A worldwide, community-maintained index of where free & legal audio lives —
and a polite tool to fetch it.** Music, audiobooks, podcasts, classical,
educational, historical. MP3, OGG, FLAC, M4B — whatever a source offers.

> MP3 is a fossil: this fetches whatever format a source offers (MP3, OGG, FLAC, M4B, …).

It's two things in one repo:

1. **The index** — [`catalog.json`](src/open_audio_fetch/catalog.json), a
   machine-readable registry of *sources* (site/API + license + robots + bulk
   path). This is the center of gravity, and **anyone can add to it with a small
   PR**. Human view: [SITES.md](SITES.md).
2. **The downloader** — pluggable adapters that fetch from those sources,
   obeying `robots.txt`, rate limits, and each item's license.

## The one hard rule: free & legal only

A source is in this project **only if** it offers the audio for free **and** its
terms/`robots.txt` permit fetching. We send an honest User-Agent, obey robots,
rate-limit every host, and **never** bypass a paywall, DRM, login, or rate cap.
Every downloaded item's license is recorded so you always know what you may keep
vs. redistribute. See [CONTRIBUTING.md](CONTRIBUTING.md) for the bar a source
must clear.

## Quick start

No dependencies — standard-library **Python 3.11+**, runnable from a plain shell
(no agent or harness required):

```bash
# Browse the index of known free-audio sources
python3 -m open_audio_fetch --catalog                 # everything
python3 -m open_audio_fetch --catalog music           # filter by category
python3 -m open_audio_fetch --validate-catalog        # check the index is well-formed & legal

# Dry-run a source (discover, download nothing)
python3 -m open_audio_fetch librivox --dry-run

# Actually fetch, into ./downloads
python3 -m open_audio_fetch librivox --out downloads --delay 1
IA_ONLY_EXTS=mp3 python3 -m open_audio_fetch internetarchive --out downloads

# Bound a run, warm-start from cache, skip works you already have
python3 -m open_audio_fetch librivox --max-bytes 2G --dedupe
python3 -m open_audio_fetch internetarchive --cache        # skip re-crawling next time

# Maintainer tools
python3 -m open_audio_fetch --validate-catalog             # legality/schema gate
python3 -m open_audio_fetch --doctor                        # live robots + reachability check

# Fill a mounted device with a mix, sized to its free space
python3 -m open_audio_fetch --device "/Volumes/MY PLAYER" --dry-run   # preview the plan
python3 -m open_audio_fetch --device "/Volumes/MY PLAYER"             # default 40% audiobooks / 40% music / 20% podcasts
python3 -m open_audio_fetch --device "/Volumes/MY PLAYER" --mix "audiobooks=70,music=30"
```

**Sync-to-device** reads the device's free space, splits a byte budget across the
mix, and runs the engine per category. Audiobooks (LibriVox) and music (Internet
Archive CC netlabels) are **key-free**; podcasts need Podcast Index credentials
and are dropped-and-reallocated if absent. It dedupes, respects a `--reserve`
margin (default 200M), and prints safe-eject guidance. Per-chapter files keep it
close to budget.

### Grow it over time (scheduled trickle)

`scripts/trickle.sh` does a bounded, cached, deduped pull — safe to run on a
schedule (re-runs only add what's new, never re-download):

```bash
# every day at 3am, add up to 500 MB of LibriVox to ~/audio-library (cron)
0 3 * * *  OAF_SOURCE=librivox OAF_MAX_BYTES=500M /path/to/repo/scripts/trickle.sh

# new podcast episodes only, since a date
OAF_SOURCE=podcastindex PODCASTINDEX_SINCE=2026-07-01 \
  PODCASTINDEX_KEY=... PODCASTINDEX_SECRET=... scripts/trickle.sh
```

On macOS, wrap it in a `launchd` plist with a `StartCalendarInterval` instead of
cron. Because every source is rate-limited and polite, a daily trickle never
hammers a host — the library just grows.

Useful flags: `--limit N`, `--max-bytes SIZE` (e.g. `500M`, `2G`) cap a run;
`--cache`/`--refresh`/`--cache-ttl` warm-start from discovered availability;
`--dedupe` skips works already downloaded (by author+title, across sources);
`--dry-run` discovers without downloading; `--delay` sets per-host politeness.

Install as a CLI with `pip install .` (gives you an `open-audio-fetch` command), a
Docker image (`docker build -t open-audio-fetch .`), or use the `Makefile`:
`make test`, `make validate`, `make catalog`, `make smoke`, `make sites`.

## The sources that ship

Verified live this session: pulled **13 GB / 1,380 public-domain files** with
zero final failures. Adapters (`✓` solid, `⚑` experimental/best-effort):

- **Audiobooks/classics:** `librivox` ✓, `listentogenius` ✓, `lit2go` ✓,
  `internetarchive` ✓, `loyalbooks` ⚑
- **Music:** `jamendo` ✓ (needs `JAMENDO_CLIENT_ID`), `freemusicarchive` ⚑,
  `musopen` ⚑ (hard ~5/day cap), `internetarchive` ✓
- **Podcasts:** `podcastindex` ✓ (needs `PODCASTINDEX_KEY`/`_SECRET`)
- **Historical:** `loc` ⚑

Plus **planned** entries in the index (no adapter yet): `ccmixter`, `openverse`,
`freesound`, `librivox_via_ia`. Run `--catalog` for the full, current list.

## How downloads are organized

```
downloads/
  <source>/<Author or Artist>/[<Album / Book / Show>/]<Title>.<ext>
  manifest.csv    # source,author,album,title,url,dest,license,status,bytes
```

Runs are **resumable** (files on disk are skipped) and **self-healing**: a
network outage pauses and waits for the connection to return instead of failing
the job, and anything still failed gets an end-of-run retry pass.

## Positioning — why this isn't a rebuilt wheel

We checked (2026-07): nothing occupies this exact niche.

- **[Openverse](https://openverse.org/)** is the closest cousin — a hosted CC
  *search* API, but over just 3 audio providers, with no audiobooks/podcasts, no
  bulk pull, and no contributable source registry. It's **complementary** — it's
  in our index as a meta-source we can consume.
- **Self-hosted servers** (Navidrome, Funkwhale, audiobookshelf) stream files
  you *already own* — they don't discover or fetch free content.
- **Human listicles** (Wikimedia Commons free-media, Hongkiat, Silverman) aren't
  machine-readable or contributable-as-code.
- **Audiobook downloaders** (audiobook-dl, Listenarr) target paid/account
  content or torrents — not a legal-free *source index*.

Our niche: a **community-contributed, machine-readable registry of free/legal
audio sources** + a **legal-first polite downloader** across *all* audio types.

## Contributing

Two ways, and the first needs no code:

1. **Add a source** — one object in `catalog.json` (validated by
   `--validate-catalog` and CI against
   [`catalog_schema.json`](src/open_audio_fetch/catalog_schema.json)).
2. **Add an adapter** — a small `SiteAdapter` with offline tests.

See [CONTRIBUTING.md](CONTRIBUTING.md). New-source proposals welcome via the
issue template.

## Licensing

- **Code:** MIT ([LICENSE](LICENSE)).
- **Catalog data:** CC0 / public domain ([LICENSE-DATA](LICENSE-DATA)) — the
  index is a public good; reuse it freely.
- **The audio itself:** keeps each source's own license (recorded per item).
  Downloading is subject to each source's terms; redistribution depends on the
  item's license.
