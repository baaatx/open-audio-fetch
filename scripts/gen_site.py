#!/usr/bin/env python3
"""Regenerate the static index website (docs/index.html) from the catalog.

    python3 scripts/gen_site.py

Served via GitHub Pages from /docs. Like SITES.md, it's a generated artifact;
a freshness test (tests/test_sites.py) fails if it drifts from catalog.json.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_audio_fetch.catalog import render_html  # noqa: E402

OUT = ROOT / "docs" / "index.html"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render_html(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
