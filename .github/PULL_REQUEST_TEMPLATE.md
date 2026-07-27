<!-- Thanks for contributing! Delete sections that don't apply. -->

## What does this PR do?



## Type
- [ ] New source (catalog.json only)
- [ ] New / improved adapter (code)
- [ ] Bug fix
- [ ] Docs / other

## Legal checklist (required for new sources/adapters)
- [ ] The source offers this audio **for free** (PD / CC0 / CC / free-for-personal).
- [ ] The source's **terms and robots.txt permit** the fetching this tool does.
- [ ] I set an accurate `license` + `license_url` and `redistributable` value.
- [ ] This does **not** bypass any paywall, DRM, login, or rate limit.

## Verification
- [ ] `python3 -m open_audio_fetch --validate-catalog` passes
- [ ] `python3 scripts/gen_sites.py` run and `SITES.md` committed (if catalog changed)
- [ ] `python3 -m unittest discover -s tests -t tests` passes
- [ ] New code has **offline** tests (no network in the suite)
