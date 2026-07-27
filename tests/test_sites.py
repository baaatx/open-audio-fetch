import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from open_audio_fetch.catalog import render_html, render_sites

_ROOT = Path(__file__).resolve().parents[1]
_SITES = _ROOT / "SITES.md"
_HTML = _ROOT / "docs" / "index.html"


class TestSitesFreshness(unittest.TestCase):
    def test_sites_md_is_up_to_date(self):
        expected = render_sites()
        actual = _SITES.read_text(encoding="utf-8")
        self.assertEqual(
            actual, expected,
            "SITES.md is stale — regenerate with: python3 scripts/gen_sites.py",
        )

    def test_index_html_is_up_to_date(self):
        expected = render_html()
        actual = _HTML.read_text(encoding="utf-8")
        self.assertEqual(
            actual, expected,
            "docs/index.html is stale — regenerate with: python3 scripts/gen_site.py",
        )


if __name__ == "__main__":
    unittest.main()
