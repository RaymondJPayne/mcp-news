# Single stage, no build tooling in the final image, no Node, no framework CDN.
# The dashboard is static files we wrote; there is nothing to compile.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MCPNEWS_CONFIG_DIR=/app/config \
    MCPNEWS_DATA_DIR=/data \
    MCPNEWS_ARCHIVE_DIR=/archive \
    MCPNEWS_WEB_DIR=/app/web

WORKDIR /app

# System deps kept deliberately minimal: certificates, and nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# The dashboard and the shipped source bundles. Compose mounts a writable
# config directory over /app/config; these are the defaults for a plain
# `docker run` with no mount.
COPY web/ ./web/
COPY config/ ./config/

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd --system --uid 10001 mcpnews \
 && mkdir -p /data /archive \
 && chown -R mcpnews:mcpnews /data /archive /app \
 && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8378
# The entrypoint fixes ownership of the mounted directories and then drops to the
# unprivileged mcpnews user. Nothing in the application runs as root.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve", "--all"]
