<!-- GENERATED FROM src/open_audio_fetch/catalog.json — DO NOT EDIT BY HAND.
     Regenerate with:  python3 scripts/gen_sites.py  -->

# The Index of Free-Audio Sources

The human-readable view of the project's index. The machine-readable source of truth is
[`catalog.json`](src/open_audio_fetch/catalog.json) (validated against [`catalog_schema.json`](src/open_audio_fetch/catalog_schema.json)); the live view is `python3 -m open_audio_fetch --catalog`.

Every source here offers audio **free for personal use** and its terms/robots permit fetching.
**Redistribute** says whether you may re-share what you download: `yes` (PD/CC0/CC-BY), `conditional`
(CC with NC/SA/ND terms), `personal-only` (e.g. podcasts), or `per-item` (varies).

**Adapter**: ✓ implemented · ⚑ experimental (best-effort) · ○ planned · ⓘ index/aggregator.

## Music

| Adapter | Source | License | Redistribute | Access |
|---|---|---|---|---|
| ○ | [ccMixter](https://ccmixter.org/) | creative-commons | conditional | api |
| ○ | [Free Music Archive (FMA)](https://freemusicarchive.org/) | creative-commons | conditional | web-scrape |
| ○ | [Freesound](https://freesound.org/) | creative-commons | conditional | api |
| ✓ | [Internet Archive — Audio](https://archive.org/details/audio) | mixed | per-item | api |
| ✓ | [Jamendo Music](https://www.jamendo.com/) | creative-commons | conditional | api |
| ○ | [Library of Congress — National Jukebox / Citizen DJ](https://www.loc.gov/collections/national-jukebox/) | mixed | per-item | api |
| ○ | [Musopen](https://musopen.org/) | public-domain | yes | web-scrape |
| ○ | [Openverse](https://openverse.org/) | mixed | per-item | api |

## Audiobooks & Classics

| Adapter | Source | License | Redistribute | Access |
|---|---|---|---|---|
| ✓ | [LibriVox](https://librivox.org/) | public-domain | yes | api |
| ○ | [LibriVox Collection on Internet Archive](https://archive.org/details/librivoxaudio) | public-domain | yes | api |
| ✓ | [Listen to Genius (Redwood Audiobooks)](https://listentogenius.com/) | public-domain | yes | web-scrape |
| ✓ | [Lit2Go (FCIT, Univ. of South Florida)](https://etc.usf.edu/lit2go/) | public-domain | yes | web-scrape |
| ✓ | [Loyal Books (formerly Books Should Be Free)](https://www.loyalbooks.com/) | public-domain | yes | web-scrape |
| ⓘ | [Open Culture](https://www.openculture.com/freeaudiobooks) | mixed | personal-only | web-scrape |

## Podcasts

| Adapter | Source | License | Redistribute | Access |
|---|---|---|---|---|
| ✓ | [Podcast Index](https://podcastindex.org/) | free-personal | personal-only | api |

---

**15 sources** — 7 implemented, 1 index-only, 7 planned.

Know a source we're missing? It must be **free & legal** (offered free, terms/robots permit fetching). See [CONTRIBUTING.md](CONTRIBUTING.md) — adding one is a small PR to `catalog.json`.
