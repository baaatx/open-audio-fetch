# Claude Code Context — open-audio-fetch

Polite downloader for **freely-offered audio** across the open web (music,
audiobooks, podcasts, classics, educational, historical). Formerly "mp3-fetcher";
renamed because MP3 is a fossil and we grab any web audio format.

## Prime directive: stay inside the rules

This project only ever fetches audio that a site **offers for free**, and it does
so **politely**. Non-negotiables when working here:

- Obey `robots.txt` (the `PoliteClient` does this; don't add bypasses).
- Send the honest `open-audio-fetch/…` User-Agent; rate-limit every host (`--delay`).
- Respect per-site limits (e.g. Musopen's ~5/day cap) — never engineer around them.
- Record each item's **license** in the catalog/manifest. PD ≠ CC ≠ personal-use.
  Downloading is fine within a site's terms; redistribution depends on the license.
- If a site's robots/ToS would forbid crawling, it does NOT belong in the catalog.

## Layout

```
src/open_audio_fetch/
  http.py         # PoliteClient: robots, throttle, retries, per-req headers, download
  fetcher.py      # BFS crawl engine, folder layout, CSV manifest, resume
  cli.py          # argparse CLI (also serves --catalog)
  catalog.json    # THE INDEX of known free-audio sources (machine-readable)
  sites/
    __init__.py   # SiteAdapter base (+ headers_for) + registry + MediaItem
    _helpers.py   # shared: strip_tags, RSS/enclosure parse, format-pref, env config
    listentogenius.py   internetarchive.py  librivox.py   jamendo.py
    podcastindex.py     lit2go.py           freemusicarchive.py
    musopen.py          loyalbooks.py       loc.py
tests/            # offline unittest suite (no network); `python3 -m unittest discover -s tests -t tests`
pyproject.toml    # stdlib-only package; `open-audio-fetch` console entry point
```

`MediaItem` carries `ext`, `license`, and `album`. Downloads:
`downloads/<source>/<Author>/[<Album>/]<Title>.<ext>` + `downloads/manifest.csv`
(`source,author,album,title,url,dest,license,status,bytes`). Both gitignored —
never commit the haul. Adapters drive the engine purely through text bodies, so
the same interface serves HTML scrapers and JSON/RSS APIs; auth'd APIs sign
requests via `headers_for`. Key-gated adapters read env (`JAMENDO_CLIENT_ID`,
`PODCASTINDEX_KEY`/`_SECRET`); Musopen self-limits via a persisted daily quota.

## Adding a source adapter

Subclass `SiteAdapter`, implement `seeds()`, `next_links()`, `extract_media()`,
`@register` it, and import it in `sites/__init__.py`. The engine handles
politeness, dedup, resume, and filing. Prefer official **APIs** over scraping
when a source offers one (Internet Archive, LibriVox, Jamendo, Podcast Index).

## The index is the center of gravity

This is a **community-contributed, machine-readable index of where free & legal
audio lives**, plus a legal-first downloader. `catalog.json` (surfaced via
`--catalog`) is the living registry; growing/refining it with accurate
license/robots data is a first-class task.

- **Contract:** `catalog_schema.json` — every source needs the legality fields
  (`license`, `license_url`, `personal_use: true`, `redistributable`,
  `robots_ok`). A source belongs here ONLY if it's free AND terms/robots permit
  fetching. Never add one you can't verify.
- **Validate:** `catalog.py` holds a stdlib validator (`validate()`) that reads
  the schema as its single source of truth. Run `--validate-catalog` (also in CI).
- **Docs are generated:** `SITES.md` is rendered from the catalog by
  `scripts/gen_sites.py`; `tests/test_sites.py` fails if it's stale. Edit the
  catalog, regenerate, commit both.
- **Contributing:** `CONTRIBUTING.md` (+ PR/issue templates). Code is MIT; the
  catalog data is CC0 (`LICENSE-DATA`).

## Must stay human-runnable (no harness)

Developing with Claude Code is fine; **running** must be a plain
`python3 -m open_audio_fetch …` / `open-audio-fetch` with no agent dependency. Don't
import agent/harness code in `src/` or `scripts/`. `tests/test_cli_smoke.py`
runs the CLI as a bare subprocess to guard this.

## Workflow

- Track work in **`backlog.md`** (items separated by `---`; statuses TODO/DOING/
  DONE/BLOCKED/IDEA).
- Test parsers offline against saved fixture HTML; only hit the network for
  smoke tests, and start with `--dry-run`. Full suite: `make test`.
- No third-party deps — standard library only, Python 3.11+.

## Running (network note)

Network calls need to leave the command sandbox in this environment. Use
`--dry-run` first to verify discovery, then a small `--max-pages` before a full
pull.
