"""Small, dependency-free helpers shared by several adapters.

Kept deliberately tiny and pure so they are trivial to unit-test offline:
HTML/entity cleanup, RSS ``<enclosure>`` parsing, audio-format detection, a
format-preference picker (so we grab one good file per track instead of every
derivative), and typed environment-variable readers for adapter config.
"""

from __future__ import annotations

import html as _html
import os
import re
from urllib.parse import urlsplit

# --- text -------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_tags(fragment: str) -> str:
    """Turn an HTML fragment into clean, single-spaced plain text."""
    text = _TAG_RE.sub(" ", fragment)
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


# --- audio formats ----------------------------------------------------------

# Extensions we consider "audio worth grabbing".
AUDIO_EXTS: tuple[str, ...] = (
    "mp3", "ogg", "oga", "opus", "m4a", "m4b", "aac", "flac", "wav", "aiff", "aif",
)

# Default download preference: universal + compact first, lossless last. A lower
# index wins when the same track is offered in several formats.
FORMAT_PREFERENCE: tuple[str, ...] = ("mp3", "m4b", "m4a", "ogg", "opus", "aac", "flac", "wav", "aiff", "aif")


def ext_of(name_or_url: str) -> str:
    """Return the lowercase extension (no dot) of a filename or URL, or ''."""
    path = urlsplit(name_or_url).path if "://" in name_or_url else name_or_url
    _, _, tail = path.rpartition("/")
    _, dot, ext = tail.rpartition(".")
    return ext.lower() if dot else ""


def is_audio(name_or_url: str) -> bool:
    return ext_of(name_or_url) in AUDIO_EXTS


def format_rank(ext: str, preference: tuple[str, ...] = FORMAT_PREFERENCE) -> int:
    """Lower is better. Unknown formats sort after all known ones."""
    ext = ext.lower().lstrip(".")
    try:
        return preference.index(ext)
    except ValueError:
        return len(preference)


def pick_best_by_format(
    candidates: list[tuple[str, str]],
    preference: tuple[str, ...] = FORMAT_PREFERENCE,
) -> tuple[str, str] | None:
    """From ``(ext, value)`` pairs pick the single best-ranked format.

    Used to collapse the many derivatives of one track (mp3 + ogg + flac …) to
    a single download. Returns None for an empty list.
    """
    if not candidates:
        return None
    return min(candidates, key=lambda pair: format_rank(pair[0], preference))


# --- RSS / enclosures -------------------------------------------------------

_ENCLOSURE_RE = re.compile(r"<enclosure\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_ITEM_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def rss_enclosures(xml: str) -> list[dict[str, str]]:
    """Return every RSS ``<enclosure>`` as a dict of its attributes.

    Each dict typically has ``url``, ``type`` and ``length``. Works on podcast
    and LibriVox feeds alike; namespace-prefixed variants are ignored (we only
    need the plain ``<enclosure>`` audio links).
    """
    out: list[dict[str, str]] = []
    for tag in _ENCLOSURE_RE.findall(xml):
        attrs = {k.lower(): _html.unescape(v) for k, v in _ATTR_RE.findall(tag)}
        if attrs.get("url"):
            out.append(attrs)
    return out


def rss_items(xml: str) -> list[str]:
    """Split a feed into its ``<item>…</item>`` chunks (crude but robust)."""
    return re.findall(r"<item\b.*?</item>", xml, re.I | re.S)


def first_title(fragment: str) -> str:
    m = _ITEM_TITLE_RE.search(fragment)
    return strip_tags(m.group(1)) if m else ""


# --- config -----------------------------------------------------------------


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())
