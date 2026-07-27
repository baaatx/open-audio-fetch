# open-audio-fetch — human-runnable convenience targets.
# Everything is plain stdlib Python; no build step, no dependencies.

PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help test validate sites sites-check smoke check catalog

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

test:  ## Run the offline test suite
	$(PYTHON) -m unittest discover -s tests -t tests

validate:  ## Validate catalog.json against the schema (legality gate)
	$(PYTHON) -m open_audio_fetch --validate-catalog

sites:  ## Regenerate SITES.md + docs/index.html from the catalog
	$(PYTHON) scripts/gen_sites.py
	$(PYTHON) scripts/gen_site.py

sites-check: sites  ## Fail if the committed SITES.md / docs are stale
	git diff --exit-code SITES.md docs/index.html

catalog:  ## Print the source index
	$(PYTHON) -m open_audio_fetch --catalog

smoke:  ## Prove the CLI runs from a plain shell
	$(PYTHON) -m open_audio_fetch --version
	$(PYTHON) -m open_audio_fetch --list-sites
	$(PYTHON) -m open_audio_fetch --validate-catalog

check: validate test  ## What CI runs: validate + full test suite
