"""Site adapters: one small class per source of free MP3s.

A SiteAdapter teaches the engine three things about a site:
  * where to start crawling (`seeds`),
  * which links to follow next (`next_links`),
  * how to pull downloadable media out of a page (`extract_media`).

The engine in `fetcher.py` handles everything else (politeness, dedup,
resume, folder layout), so adding a new site is just a new adapter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaItem:
    """One downloadable audio file plus enough metadata to file it neatly.

    ``ext`` carries the real container (mp3/ogg/flac/m4b/zip/…) so the engine
    never assumes MP3. ``license`` records the item's rights so the manifest can
    honor the prime directive (PD ≠ CC ≠ personal-use). ``album`` is an optional
    middle folder for chaptered works (an audiobook, a concert, a podcast show).
    """

    url: str  # absolute URL of the audio file
    title: str  # work/track title, e.g. "The Tell-Tale Heart"
    author: str = ""  # creator/author, used as the top folder
    source: str = ""  # adapter name, for logging/manifest
    ext: str = "mp3"  # file extension WITHOUT the dot
    license: str = ""  # rights string / license URL for this specific item
    album: str = ""  # optional middle folder (book, album, concert, show)


class SiteAdapter:
    """Interface every source adapter implements.

    The engine drives an adapter purely through text bodies (`get_text`), which
    works equally for HTML pages and JSON/RSS API responses — an adapter just
    dispatches on the URL shape it recognizes. Anything requiring authentication
    can supply per-request headers via `headers_for`.
    """

    name: str = "base"
    base_url: str = ""

    def seeds(self) -> list[str]:
        """Return the initial page/API URLs to begin crawling from."""
        raise NotImplementedError

    def next_links(self, page_url: str, body: str) -> list[str]:
        """Return absolute URLs of further pages/endpoints worth fetching."""
        return []

    def extract_media(self, page_url: str, body: str) -> list[MediaItem]:
        """Return the downloadable MediaItems found in this body."""
        raise NotImplementedError

    def headers_for(self, url: str) -> dict[str, str]:
        """Extra request headers for `url` (e.g. API auth). Default: none."""
        return {}


_REGISTRY: dict[str, type[SiteAdapter]] = {}


def register(cls: type[SiteAdapter]) -> type[SiteAdapter]:
    _REGISTRY[cls.name] = cls
    return cls


def get_adapter(name: str) -> SiteAdapter:
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown site {name!r}; available: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[name]()


def available() -> list[str]:
    return sorted(_REGISTRY)


# Import built-in adapters so they self-register on package import.
from . import listentogenius as _listentogenius  # noqa: E402,F401
from . import internetarchive as _internetarchive  # noqa: E402,F401
from . import librivox as _librivox  # noqa: E402,F401
from . import jamendo as _jamendo  # noqa: E402,F401
from . import podcastindex as _podcastindex  # noqa: E402,F401
from . import lit2go as _lit2go  # noqa: E402,F401
from . import freemusicarchive as _freemusicarchive  # noqa: E402,F401
from . import musopen as _musopen  # noqa: E402,F401
from . import loyalbooks as _loyalbooks  # noqa: E402,F401
from . import loc as _loc  # noqa: E402,F401
