# syntax=docker/dockerfile:1
# Root build context for deployments that expect a Dockerfile in the repository
# root. This image serves the web app, API and worker through one public port.
# The component Dockerfiles remain available for the Docker Compose deployment.

FROM node:22-bookworm-slim AS web-deps
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM web-deps AS web-builder
# Tailwind imports the repository's shared design tokens from ../design.
COPY design/tokens.json /design/tokens.json
COPY web/ ./
ENV NEXT_TELEMETRY_DISABLED=1 \
    BUILD_STANDALONE=1
RUN npm run build

FROM python:3.11-slim-bookworm AS backend-deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
COPY backend/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.11-slim-bookworm AS runtime
LABEL org.opencontainers.image.source="https://github.com/dmoshiur/armx.cloudcampbd"
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates gettext-base libatomic1 libstdc++6 nginx supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 armx \
    && useradd --uid 10001 --gid armx --home-dir /app --no-create-home --shell /usr/sbin/nologin armx

# The standalone server needs Node, but not npm or the build-time dependencies.
COPY --from=web-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=backend-deps /opt/venv /opt/venv
WORKDIR /app
COPY --from=web-builder --chown=armx:armx /app/.next/standalone ./web/
COPY --from=web-builder --chown=armx:armx /app/.next/static ./web/.next/static/
COPY --from=web-builder --chown=armx:armx /app/public ./web/public/
COPY --chown=armx:armx backend/ ./backend/
# Backend project linting also reads the repository's shared token source.
COPY --chown=armx:armx design/tokens.json ./design/tokens.json
COPY deploy/runtime/ ./deploy/runtime/
RUN chmod 0755 /app/deploy/runtime/entrypoint.sh \
    && mkdir -p /data/workspace /data/media \
    && chown -R armx:armx /data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=10000 \
    ENV=production \
    DEBUG=false \
    AUTO_CREATE_TABLES=false \
    LLM_PROVIDER=groq \
    REQUIRE_TURSO_IN_PRODUCTION=true \
    TURSO_REPLICA_PATH=/data/turso-replica.db \
    DATABASE_URL=sqlite+aiosqlite:////data/armx.db \
    PROJECT_WORKSPACE=/data/workspace

USER armx
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD ["python", "/app/deploy/runtime/healthcheck.py"]
ENTRYPOINT ["/app/deploy/runtime/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/app/deploy/runtime/supervisord.conf"]
