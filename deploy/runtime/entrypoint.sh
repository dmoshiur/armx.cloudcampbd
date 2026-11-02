#!/bin/sh
set -eu

# Render and other Docker hosts supply PORT at runtime, not at build time.
PORT="${PORT:-10000}"
case "$PORT" in
    ''|*[!0-9]*) echo "PORT must be an integer between 1024 and 65535." >&2; exit 1 ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ] || [ "$PORT" -eq 3000 ] || [ "$PORT" -eq 8000 ]; then
    echo "PORT must be between 1024 and 65535 and must not use reserved internal ports 3000 or 8000." >&2
    exit 1
fi
export PORT

# Render provides its public HTTPS URL. Explicit application settings win.
if [ -z "${WEB_ORIGIN:-}" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
    export WEB_ORIGIN="$RENDER_EXTERNAL_URL"
fi
if [ -z "${CORS_ORIGINS:-}" ] && [ -n "${WEB_ORIGIN:-}" ]; then
    export CORS_ORIGINS="$WEB_ORIGIN"
fi
if [ "${ENV:-production}" = "production" ] && [ -z "${JWT_SECRET:-}" ]; then
    echo "JWT_SECRET is required in production. Set a long random value in the deployment environment." >&2
    exit 1
fi

mkdir -p "${PROJECT_WORKSPACE:-/data/workspace}"
# Only substitute PORT; nginx's own $variables must remain intact.
envsubst '$PORT' < /app/deploy/runtime/nginx.conf > /tmp/armx-nginx.conf
nginx -t -c /tmp/armx-nginx.conf

# Apply migrations before starting any application process. The existing typed
# production guards also run here: never invent secrets or disable validation.
cd /app/backend
alembic upgrade head
cd /app

exec "$@"
