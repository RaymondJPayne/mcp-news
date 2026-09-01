# Single stage, no build tooling in the final image, no Node, no framework CDN.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept deliberately minimal.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# The dashboard is static files we wrote, served by our own API. No build step.
COPY web/ ./web/
COPY config/ ./config/

RUN useradd --system --uid 10001 mcpnews \
 && mkdir -p /data /archive \
 && chown -R mcpnews:mcpnews /data /archive /app
USER mcpnews

EXPOSE 8378
ENTRYPOINT ["mcpnews"]
CMD ["serve", "--all"]
