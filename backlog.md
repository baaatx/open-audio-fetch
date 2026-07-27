# open-audio-fetch backlog

Running backlog. Items are separated by a line containing only `---`.
Open items are ordered **most-impactful-first** and tagged `P0`–`P3`:

- **P0** — make the core reliably correct (what we already ship should truly work)
- **P1** — deliver the headline "fill my device with free audio" value
- **P2** — speed + the community-index differentiators
- **P3** — polish, reach, and later infra

Statuses: TODO · DOING · DONE · BLOCKED · IDEA. Keep DONE items for history.

---

## Mission (why this project exists)

A **worldwide, community-maintained index of where free & legal audio lives** —
music, audiobooks, podcasts, classical, educational, historical — paired with a
**polite, legal-first downloader** that can actually pull it onto your disk.

Two halves, one project: **the index** (`catalog.json`, a contributable registry
of sources) and **the downloader** (pluggable `SiteAdapter`s). **Non-negotiable:
legal & free only** — a source belongs here only if it offers audio for free and
its terms/robots permit fetching. No paywall bypass, DRM stripping, torrents, or
rate-limit evasion, ever. Prior art checked (2026-07-26): no project occupies
this niche; see README "Positioning".

---

## DONE: Foundation — engine, 10 adapters, tests, resilience

stdlib-only package; pluggable `SiteAdapter`; polite HTTP client (robots,
throttle, retries). `MediaItem` with `ext`/`license`/`album`; format-aware
filing; CSV manifest with per-item license. 10 adapters (listentogenius,
internetarchive, librivox, jamendo, podcastindex, lit2go, freemusicarchive,
musopen, loyalbooks, loc). Network-outage self-healing (classify
permanent/transient/outage; wait out outages; end-of-run retry pass) — proven
live. Verified live: pulled 13 GB / 1,380 PD files, 0 final failures.

---

## DONE: OSS reframe — legal-first index, validation, community model

(commit 9574526) Catalog v2 with a legal-first `catalog_schema.json` (mandatory
license/rights fields); stdlib validator + `--validate-catalog` + CI gate;
`SITES.md` generated from the catalog with a freshness test; `CONTRIBUTING.md`,
PR/issue templates, `CODE_OF_CONDUCT.md`; `LICENSE` (MIT code) + `LICENSE-DATA`
(CC0 index); GitHub Actions CI (validate + tests + CLI smoke, ubuntu/macOS,
3.11–3.13); README repositioned; human-runnable guard (subprocess smoke test +
Makefile). Added 2 verified sources (Openverse, Freesound); corrected LoC to
mixed/per-item; dropped Pixabay (unverifiable). 90 tests green, 15 sources.

---

## DONE: P0 — URL encoding + download integrity

`encode_url()` percent-encodes outgoing URLs (fixed archive.org/LibriVox
spacey zip URLs; verified live). `download()` checks `Content-Length` vs bytes
written and raises a retryable `IncompleteDownload` on a short read — no
truncated file is ever accepted as done.

---

## DONE: P0 — verified & hardened the experimental adapters

Live-checked all four. loyalbooks: fixed seeds -> promoted to implemented. FMA
(JS SPA), musopen (Cloudflare 403s our UA on robots), loc (robots-refused +
streaming-only): honestly downgraded to planned with accurate `robots_ok` and
notes. ccMixter also found robots-blocked (`Disallow: /api/`). Net: 7 adapters
that actually work, 0 unproven claims.

---

## DONE: P1 — run caps `--limit N` / `--max-bytes`

Stop after N files or a byte budget (binary units, e.g. `--max-bytes 2G`).
Enforced in the crawl loop; dry-run ignores caps. Verified live.

---

## DONE: P1 — sync-to-device mode (`--device`, 40/40/20 mix)

`--device PATH` fills a mounted player, sized to its free space (minus
`--reserve`, default 200M), split across `--mix` (default audiobooks=40,
music=40, podcasts=20) by running the engine per category. Key-free by default:
audiobooks = LibriVox **per-chapter** (chapter-sized files respect the budget;
whole-book zips would overshoot by 100s of MB), music = Internet Archive CC
`netlabels`. Podcasts need Podcast Index keys — dropped and reallocated if
absent. Dedupes; prints safe-eject guidance. Verified live end-to-end (budget
respected within one file/category; correct per-category filing). Pure planning
(mix/budget/reallocation) unit-tested.

---

## DONE: P2 — local availability cache (`--cache`)

Opt-in warm-start cache of discovered items under
`~/.cache/open-audio-fetch/availability/`; fresh cache skips crawling entirely.
`--refresh` re-crawls, `--cache-ttl` sets freshness. Degrade-safe; deterministic.
Falls back to the committed repo shard so a fresh clone warm-starts offline.

---

## DONE: P2 — repo availability index + job robot

`scripts/build_availability.py` (the bot) writes sharded, deterministic
`availability/<source>.json` — non-authoritative, git-conflict-resistant, and
what `--cache` warm-starts from. `availability/README.md` documents the
convention; demo shards committed.

---

## DONE: P2 — ccMixter investigated; `--doctor` health-check

ccMixter can't be an adapter: robots `Disallow: /api/` (documented, kept
planned). `--doctor` live-checks every source (robots + reachability against the
real endpoint via `check_url`) and exits nonzero on a broken active source; it
already caught Openverse's bot-disallowed audio endpoint. Index growth is done
with live verification rather than optimistic adds.

---

## DONE: P3 — cross-source dedupe (`--dedupe`), static website, Dockerfile

`--dedupe` skips a work already downloaded (normalized author+title, across
sources and runs via the manifest). `docs/index.html` is a generated,
self-contained site (freshness-tested). `Dockerfile` gives a dep-free portable
image.

---

## DEFERRED (P3): bounded concurrency, SQLite, resume frontier

Judged not worth doing now (documented so we don't relitigate):
- **Bounded concurrency** — real politeness risk (parallel fetches vs per-host
  rate-limit); the tool is I/O-bound on a courteous delay by design. Skip unless
  a compelling need appears, and only with strict per-host serialization.
- **SQLite manifest** — the CSV manifest works and is grep-friendly; a DB is a
  large add for marginal "what do I have" query value. Revisit if the library
  grows past CSV's comfort.
- **Resume frontier persistence** — largely subsumed by the availability cache
  (warm-start avoids re-crawling); resume-by-file-existence already prevents
  re-downloads. Low marginal value now.

---

## DONE: P3 — cross-packaging dedupe (IA `IA_PREFER`)

When an Internet Archive item ships both per-chapter files and a whole-book
bundle (M4B / "complete" / "partN"), keep one packaging (default chapters).
Verified live (LibriVox item -> 50 mp3, 0 m4b). The remaining fully-general case
(same audio across *different sources* with no shared title) would need audio
fingerprinting — out of scope.

---

## DONE: IDEA — scheduled polite trickle

`scripts/trickle.sh` does a bounded (`--max-bytes`), cached, deduped pull that's
safe to cron/launchd — re-runs only add what's new. `PODCASTINDEX_SINCE`
new-episodes-only filter for podcasts. README documents cron + launchd recipes.

---

## DONE: Renamed project -> open-audio-fetch

The current name (`open-audio-fetch` / `open_audio_fetch` / `slurp` / `Fetcher`) is
**everywhere** — ~110 line hits across ~30 files, and it's baked into structural
surfaces, not just prose. When we pick a new name, treat this as one atomic,
mechanical rename (avoid partial states) touching:

**Package & import identity**
- Directory `src/open_audio_fetch/` → `src/<newname>/`.
- Every `import open_audio_fetch` / `from open_audio_fetch …` (package modules + all
  tests via PYTHONPATH). ~14 files import it.
- `src/open_audio_fetch/__init__.py` docstring/identity.

**Distribution (pyproject.toml)**
- `[project].name = "open-audio-fetch"`.
- `[project.scripts]` console entry `open-audio-fetch = "open_audio_fetch.cli:main"`.
- `[tool.hatch.build…]` package path `src/open_audio_fetch`.

**Runtime strings (user-visible / external)**
- `http.py` `USER_AGENT = "open-audio-fetch/0.1 …"` — this is sent to every host as
  our polite identity; pick the new name deliberately and keep the honest URL.
- `cli.py` `prog="open-audio-fetch"` and the `--version` string.
- Internal env var `OPEN_AUDIO_FETCH_DRY_RUN` (set in cli, read in `musopen.py`) —
  rename both sides together.
- Local cache dir `~/.cache/open-audio-fetch/…` (cache.py) — path changes; old
  caches just orphan and rebuild (fine).

**Code identifiers (cosmetic, optional but tidy)**
- Class `Fetcher` (engine) + local `fetcher` variables.

**Docs / meta / generated**
- README.md, CONTRIBUTING.md, CLAUDE.md, CODE_OF_CONDUCT.md, LICENSE +
  LICENSE-DATA ("open-audio-fetch contributors"), Dockerfile, Makefile.
- `.github/` PR + issue templates, `ci.yml`.
- `scripts/*.sh` + `scripts/gen_*.py` + `build_availability.py`.
- **Generated artifacts** — regenerate after rename: `SITES.md` (gen_sites.py),
  `docs/index.html` (gen_site.py). `catalog.json` `_about` text + the schema
  `$id` URL both mention the name.
- The top-level repo folder `open-audio-fetch/` and any GitHub URLs/remote.

Note: this is the project's *second* rename (mp3-fetcher → open-audio-fetch), so
there's precedent. The download tree layout (`<source>/<author>/…`) is
name-independent, so existing hauls are unaffected. A single find/replace pass +
`git mv` of the package dir + regenerate docs + full test run should do it.

---

## TODO: Make lit2go indexable (crawl-order efficiency)

lit2go works for a normal run (default `--max-pages 5000` reaches its chapter
pages), but it's a 3-level site (books → book → chapter) and the engine's BFS
exhausts ~200+ listing pages before any chapter, so `build_availability.py`
can't reach its audio within a sane page budget — it's the one buildable source
absent from the committed index. Options: seed only `books/` and follow
book→chapter with priority; or add optional depth-first / priority crawling to
the engine. Low priority (direct runs are fine); purely an indexing nicety.

---

## Open backlog: rename + lit2go-indexing above; everything else DONE

All planned/idea items are DONE. The core solution is complete: index -> validate
-> discover -> fetch (resilient, polite, legal) -> fill a device / trickle over
time. Remaining: the rename (later) and the DEFERRED note below.

---
