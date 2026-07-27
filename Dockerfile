# open-audio-fetch — portable container. Stdlib-only, so this is tiny and dep-free.
#
# Build:  docker build -t open-audio-fetch .
# Run:    docker run --rm -v "$PWD/downloads:/downloads" open-audio-fetch --catalog
#         docker run --rm -v "$PWD/downloads:/downloads" \
#                    open-audio-fetch librivox --out /downloads --delay 1
# Keys:   pass API keys via -e, e.g. -e JAMENDO_CLIENT_ID=xxxxxxxx
FROM python:3.12-slim

# No third-party dependencies to install — the whole point of stdlib-only.
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Downloads land here; mount a host volume over it to keep the haul.
VOLUME ["/downloads"]
WORKDIR /downloads

# The console entry point installed by pyproject.
ENTRYPOINT ["open-audio-fetch"]
CMD ["--catalog"]
