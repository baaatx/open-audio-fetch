# Contributing to open-audio-fetch

Thanks for helping build a **worldwide index of where free & legal audio lives**
— and a polite tool to fetch it. There are two ways to contribute, and the first
is deliberately tiny:

1. **Add a source to the index** — a small PR to `catalog.json`. You don't need
   to write any code.
2. **Add or improve an adapter** — the Python that actually downloads from a
   source.

Everything here is standard-library Python 3.11+ with **no runtime
dependencies**, and it must stay **human-runnable from a plain shell** (no agent
or harness required to run it).

---

## The one hard rule: free & legal only

A source belongs in this project **only if both** are true:

1. **It offers the audio for free.** Public domain, Creative Commons, CC0, or
   explicitly free-for-personal-listening (e.g. podcast RSS). No paywalled,
   account-gated, or DRM'd content.
2. **Its terms and `robots.txt` permit the fetching we do.** If a site's ToS or
   robots forbids crawling/downloading, it does **not** belong here — no
   exceptions, no "just scrape it anyway".

We also **never** engineer around a limit a host sets (rate caps, quotas). We
send an honest User-Agent, obey `robots.txt`, and rate-limit every host.

**`robots.txt` is obeyed strictly — no exceptions.** This is a deliberate policy
choice, not a legal necessity: `robots.txt` is a voluntary convention, and much
of this content is genuinely free to download by hand. We honor it anyway, as
the core of being a *polite* downloader. Concretely:

- If `robots.txt` disallows the paths we'd fetch, the source stays `planned`
  with `robots_ok: false` — **even if its content is free**, and **even if it
  offers a "public" API**. Examples we've had to keep out on these grounds:
  ccMixter (`Disallow: /api/`), Openverse (`Disallow: /v1/audio/`), Musopen
  (blocks our User-Agent). Their audio is free; we still don't crawl them.
- Do **not** propose working around a robots block (rotating User-Agents,
  ignoring `robots.txt`, "just for the API", headless browsers to dodge it).
  Such PRs will be declined regardless of how free the content is.

If you're not sure whether a source qualifies, open a "new source" issue and
we'll figure out the rights together before any code is written.

---

## Adding a source (no code)

Add one object to the `sources` array in
[`src/open_audio_fetch/catalog.json`](src/open_audio_fetch/catalog.json). The contract
is [`catalog_schema.json`](src/open_audio_fetch/catalog_schema.json); every field
below is required unless marked optional:

```jsonc
{
  "id": "my_source",                       // lowercase [a-z0-9_], unique
  "name": "My Source",
  "url": "https://example.org/",
  "categories": ["music"],                 // from the schema's category enum
  "license": "creative-commons",           // public-domain|cc0|creative-commons|free-personal|mixed
  "license_url": "https://example.org/license",   // REQUIRED: page stating the rights
  "terms_url": "https://example.org/tos",  // optional (null if same as license_url)
  "personal_use": true,                    // must be true — the baseline for inclusion
  "redistributable": "conditional",        // yes|conditional|no|mixed
  "robots_ok": true,                       // robots/terms permit our fetching
  "robots": "Short human note on the robots/terms posture",  // optional
  "access": "api",                         // api|feed|web-scrape|hybrid
  "api": "https://api.example.org/v1",     // optional
  "bulk": "How to page/bulk-download",     // optional
  "formats": ["mp3"],
  "adapter_status": "planned",             // planned until an adapter ships
  "tags": [],                              // optional
  "added_by": "your-github-handle",
  "verified": "2026-07-26",                // ISO date you confirmed the rights (or null)
  "notes": "Anything useful"               // optional
}
```

Then validate locally (this is exactly what CI runs):

```bash
python3 -m open_audio_fetch --validate-catalog
python3 scripts/gen_sites.py          # regenerate SITES.md
python3 -m unittest discover -s tests -t tests
```

Commit both `catalog.json` **and** the regenerated `SITES.md` (a test enforces
they stay in sync). By contributing catalog data you agree to release it under
**CC0** (see [LICENSE-DATA](LICENSE-DATA)).

---

## Adding an adapter (code)

An adapter teaches the engine how to fetch from one source. Subclass
`SiteAdapter` in `src/open_audio_fetch/sites/`, implement:

- `seeds()` — starting page/API URLs
- `next_links(url, body)` — further URLs to follow (`body` is text: HTML *or*
  JSON/RSS — dispatch on the URL shape)
- `extract_media(url, body)` — the downloadable `MediaItem`s in a body
- `headers_for(url)` — *optional*, per-request auth headers (see
  `podcastindex.py`)

Then `@register` it and import it in `sites/__init__.py`. Study
[`internetarchive.py`](src/open_audio_fetch/sites/internetarchive.py) (JSON API) or
[`listentogenius.py`](src/open_audio_fetch/sites/listentogenius.py) (scraper) as
templates. Set each `MediaItem`'s `license` so it lands in the manifest.

**Tests are required** and must be **offline** — parse fixture HTML/JSON, never
hit the network in the test suite. Add a parser test mirroring the real response
shape (see `tests/test_adapters_api.py` / `tests/test_adapters_scrape.py`).

Prefer an official **API** over scraping when one exists. Respect rate limits;
if a source is quota-gated, hard-respect the quota (see `musopen.py`).

---

## Code style & checks

- Standard library only — no third-party runtime deps.
- Match the surrounding style; keep functions small and documented.
- Run the full suite before pushing: `python3 -m unittest discover -s tests -t tests`.
- Keep it human-runnable: no import of agent/harness code in `src/` or `scripts/`.

By contributing code you agree to license it under the repo's **MIT** license.
