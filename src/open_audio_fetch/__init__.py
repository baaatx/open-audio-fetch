"""open-audio-fetch: politely download freely-offered audio into a clean folder layout.

Formats are incidental — MP3, OGG, M4B, FLAC, whatever a source offers. The name
"mp3" is a fossil; this tool slurps free *audio* from the open web.

Design goals:
  * Respect the rules: obey robots.txt, send an honest User-Agent, rate-limit.
  * Only fetch media a site explicitly offers as a free download.
  * Resume-friendly: skip files already on disk; never leave half files behind.
  * Pluggable: each source is a small SiteAdapter, so new free-mp3 sites are cheap.
"""

__version__ = "0.1.0"
