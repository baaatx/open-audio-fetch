"""Adapter for listentogenius.com (Redwood Audiobooks).

The site explicitly offers "free audio downloads of the works of important
authors" — public-domain classic literature read by professional narrators.
robots.txt is fully permissive (`User-agent: * / Disallow:`).

Page shapes observed:
  * index.php / titles.php / categories.php / category1.php/<Name>
      -> listing pages linking to author.php/<id> and author.php/<id>/<workId>
  * author.php/<id>/<workId>
      -> a work page containing:
           <h1>Author Name</h1>
           <h2 class="wktit">...<span class="bigger">WORK TITLE</span></h2>
           <a href="recordings2/File.mp3" target="_blank">alternate download link</a>
      (some works list several recordings -> several mp3 hrefs)
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import urljoin

from . import MediaItem, SiteAdapter, register

# recordings2/Foo.mp3, recordings/Bar.mp3, etc.
_MP3_RE = re.compile(r"""["'(]\s*(recordings\d*/[^"'()]+?\.mp3)\s*["')]""", re.I)
# Internal content links worth following.
_LINK_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_SPAN_RE = re.compile(
    r'<span[^>]*class\s*=\s*["\']bigger["\'][^>]*>(.*?)</span>', re.I | re.S
)

# Only follow links that lead to more listings or work pages.
_FOLLOW_PREFIXES = ("author.php", "category1.php", "categories.php", "titles.php")


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


@register
class ListenToGenius(SiteAdapter):
    name = "listentogenius"
    base_url = "https://listentogenius.com/"

    def seeds(self) -> list[str]:
        # index.php enumerates authors; titles.php enumerates every title;
        # categories.php fans out to each genre. Together they reach every work.
        return [
            urljoin(self.base_url, "index.php"),
            urljoin(self.base_url, "titles.php"),
            urljoin(self.base_url, "categories.php"),
        ]

    def next_links(self, page_url: str, html: str) -> list[str]:
        links: list[str] = []
        for href in _LINK_RE.findall(html):
            href = _html.unescape(href.strip())
            if href.lower().startswith(_FOLLOW_PREFIXES):
                links.append(urljoin(self.base_url, href))
        return links

    def extract_media(self, page_url: str, html: str) -> list[MediaItem]:
        paths = list(dict.fromkeys(_MP3_RE.findall(html)))  # dedupe, keep order
        if not paths:
            return []

        author = ""
        m = _H1_RE.search(html)
        if m:
            author = _strip_tags(m.group(1))

        title = ""
        m = _TITLE_SPAN_RE.search(html)
        if m:
            title = _strip_tags(m.group(1))

        items: list[MediaItem] = []
        for i, path in enumerate(paths):
            url = urljoin(self.base_url, path)
            # When a page bundles several recordings, keep titles distinct by
            # falling back to the file's own name.
            stem = re.sub(r"\.mp3$", "", path.rsplit("/", 1)[-1], flags=re.I)
            item_title = title if (title and len(paths) == 1) else (title and f"{title} ({stem})" or stem)
            items.append(
                MediaItem(
                    url=url,
                    title=item_title or stem,
                    author=author or "Unknown",
                    source=self.name,
                    ext="mp3",
                    license="public-domain",
                )
            )
        return items
