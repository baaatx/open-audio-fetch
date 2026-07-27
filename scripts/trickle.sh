#!/usr/bin/env bash
#
# Polite scheduled trickle — grow the library a little on each run, safe to
# schedule (cron / launchd). Because the engine skips files already on disk and
# `--dedupe` skips works you already have, re-running only adds what's new, and
# `--cache` avoids re-crawling. Bounded by --max-bytes so no single run runs away.
#
# Configure via env (all optional):
#   OAF_SOURCE     source id to pull        (default: librivox)
#   OAF_OUT        output dir               (default: ~/audio-library)
#   OAF_DEVICE     if set, sync-to-device instead of pulling one source
#   OAF_MAX_BYTES  per-run byte budget      (default: 500M)
#   OAF_DELAY      per-host politeness secs  (default: 2)
#   plus any adapter env (JAMENDO_CLIENT_ID, PODCASTINDEX_KEY/_SECRET,
#   PODCASTINDEX_SINCE=YYYY-MM-DD for new-episodes-only, IA_COLLECTION, …)
#
# Examples:
#   OAF_SOURCE=librivox OAF_MAX_BYTES=1G scripts/trickle.sh
#   OAF_DEVICE="/Volumes/SWIM PRO" scripts/trickle.sh
#   OAF_SOURCE=podcastindex PODCASTINDEX_SINCE=2026-07-01 \
#     PODCASTINDEX_KEY=... PODCASTINDEX_SECRET=... scripts/trickle.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"

OUT="${OAF_OUT:-$HOME/audio-library}"
MAX="${OAF_MAX_BYTES:-500M}"
DELAY="${OAF_DELAY:-2}"

if [ -n "${OAF_DEVICE:-}" ]; then
  exec python3 -m open_audio_fetch --device "$OAF_DEVICE" \
    --max-bytes "$MAX" --delay "$DELAY" --cache
fi

SOURCE="${OAF_SOURCE:-librivox}"
mkdir -p "$OUT"
exec python3 -m open_audio_fetch "$SOURCE" --out "$OUT" \
  --max-bytes "$MAX" --delay "$DELAY" --cache --dedupe --quiet
