#!/usr/bin/env python3
"""Regenerate SITES.md from the catalog. Run from the repo root:

    python3 scripts/gen_sites.py

SITES.md is a generated artifact — edit catalog.json, then run this. CI checks
that the checked-in SITES.md matches (see tests/test_sites.py).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from open_audio_fetch.catalog import render_sites  # noqa: E402

OUT = ROOT / "SITES.md"


def main() -> int:
    OUT.write_text(render_sites(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
