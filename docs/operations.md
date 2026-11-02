# Operations: deploy, backup, restore, monitoring

## Staged deployment

1. **Local** — `make install && make dev && make test`. 68 tests must pass.
2. **Staging** — same compose file with `ENV=staging`, a staging Postgres and
   `LLM_PROVIDER=mock` (so nothing costs money). Walk the checklist below.
3. **Production** — `ENV=production`, real keys, real domains. The app refuses to
   boot if `JWT_SECRET` is a placeholder, if `AUTO_CREATE_TABLES` is true, or if
   `WEB_ORIGIN` is not https.

### Pre-flight checklist

- [ ] `JWT_SECRET` is ≥ 32 random bytes (`openssl rand -base64 48`)
- [ ] `POSTGRES_PASSWORD`, `REDIS_PASSWORD` set
- [ ] `ANTHROPIC_API_KEY` set; `LLM_PROVIDER=claude`
- [ ] SMTP configured (password reset fails closed without it in production)
- [ ] `WEB_ORIGIN` / `CORS_ORIGINS` are the real https origin
- [ ] `GITHUB_ALLOWED_TARGETS` (or `GITHUB_DEFAULT_ORG`) set before `PIPELINE_MODE=live`
- [ ] `alembic upgrade head` has run (the api container does it on boot)
- [ ] First admin created via the CLI, then verified by logging in
- [ ] Kill-switch released and `/api/health` returns `status: ok`

## Single-container hosts (e.g. Render)

The repository-root `Dockerfile` is for a Docker host that builds the repository
root rather than `web/` or `backend/`. Keep these settings:

| Setting | Value |
|---|---|
| Build context | Repository root (`.`) |
| Dockerfile path | `./Dockerfile` |
| Public port | Runtime `PORT`; default `10000` (Render detects the exposed port) |
| Health check | `/api/health` |
| Persistent data directory | `/data` (database, workspace and media) |
| Runtime user | Non-root UID/GID `10001` |

Nginx serves both the web app and `/api/*` on the same origin. FastAPI and Next.js
bind only to container loopback; the worker runs alongside them under Supervisor.
Ports `3000` and `8000` are reserved internally. Do not override the image command
with `next start` or `uvicorn`: that would omit the other services and the proxy.
The entrypoint renders the nginx port, validates configuration, runs
`alembic upgrade head`, then starts Supervisor. A failed migration stops startup.

### Required environment

- `ENV=production` (the image default), `DEBUG=false`, and
  `AUTO_CREATE_TABLES=false`. Do not weaken these guards to make a deploy pass.
- `JWT_SECRET`: a long random secret, generated with `openssl rand -base64 48`.
  Keep it stable across restarts; there is no insecure production fallback.
- `WEB_ORIGIN`: the actual public HTTPS origin. On Render only, unset values are
  derived from `RENDER_EXTERNAL_URL`. An explicit value always wins.
- `CORS_ORIGINS`: defaults to `WEB_ORIGIN` in the root entrypoint when unset.
- `DATABASE_URL`: a managed PostgreSQL connection URL for production. The backend
  accepts Render's `postgres://` and `postgresql://` forms and uses asyncpg.
- `REDIS_URL`: a managed Redis URL for shared rate limits and gateway state.
- `LLM_PROVIDER=mock` is the image default and is labelled offline. For Claude,
  set `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY`; for OpenAI, set
  `LLM_PROVIDER=openai` and `OPENAI_API_KEY`.

The default SQLite URL is `sqlite+aiosqlite:////data/armx.db`; project files and
media default to `/data/workspace` and `/data/media`. For a **single-instance
evaluation only**, attach a persistent disk at `/data` instead of configuring
Postgres. Ensure the mounted directory is writable by UID `10001`; a disk initialized
with different ownership must be corrected by the host before startup. Do not run
multiple replicas against SQLite or a local disk. Without a persistent disk,
SQLite data and media are ephemeral. External Postgres does not make uploaded
media persistent: mount `/data` for media/workspace storage as well.

This image does not start PostgreSQL or Redis inside the container. Use managed
services or the existing Compose stack. Deploy one instance until migration
concurrency and shared storage are handled by your infrastructure. The host must
allow at least the image's 60-second health-check start period; migrations and
three Python/Node processes need more startup time than a static site.

Build and smoke-test locally with Docker:

```bash
docker build -t armx .
docker run --rm --name armx-check -p 8080:8080 \
  -e PORT=8080 -e ENV=development \
  -e WEB_ORIGIN=http://localhost:8080 armx
# In another terminal:
curl -fsS http://localhost:8080/api/health
curl -fsS http://localhost:8080/login >/dev/null
```

This development check uses a temporary SQLite database. The GitHub Actions
workflow builds the root image and checks migrations, the web page, API health
and signup through the public port. It also runs the backend and entrypoint tests.

## Backup and restore

```bash
# nightly (cron) — logical dump + audit export
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U armx -Fc armx > backups/armx-$(date +%F).dump
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" https://armx.example/api/admin/audit?limit=200000 \
  > backups/audit-$(date +%F).json

# restore into a fresh database
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_restore -U armx -d armx --clean --if-exists < backups/armx-2026-10-30.dump
```

Generated project files live in the `appdata` volume (`/data/workspace`); they are
reconstructible from the `generated_projects.files` column, so the database dump is
sufficient for a full recovery. Media assets live in `/data/media` and should be
copied with the same cadence.

**Restore drill (run quarterly):** restore into a scratch stack, sign in, verify
`/api/admin/audit/verify` returns `ok: true`, open a conversation, generate a site,
then destroy the scratch stack.

## Monitoring and alerting

| Signal | Source | Alert |
|---|---|---|
| API liveness | `GET /api/health` | 2 consecutive failures → page |
| Planner errors | audit `assistant.error` | > 5/min → warn (key or quota issue) |
| Approval backlog | `GET /api/admin/overview → pending_approvals` | > 20 for 10 min → investigate |
| Denied tool calls | audit `tool.denied` | spike → possible abuse or injection attempt |
| Kill-switch state | audit `admin.kill_switch` | engaged → notify the owner immediately |
| Audit chain | `GET /api/admin/audit/verify` (hourly) | `ok: false` → security incident |
| Deploy failures | audit `tool.executed` where `tool=web_deploy` and status=error | 3 in a row → check tokens/allowlist |

A simple external check: `curl -fsS https://armx.example/api/health | jq -e '.status=="ok"'`.

## Upgrades

```bash
git pull
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml run --rm api alembic upgrade head
docker compose -f deploy/docker-compose.yml up -d
```

Migrations are additive-first: deploy the new code after the migration, and keep the
previous image tagged for a one-command rollback.

## Incident playbook

1. **Suspicious tool activity** → engage the kill-switch (admin UI). Everything halts
   except read-only health checks. Then read the audit trail and `approvals`.
2. **Lost admin access** → run `python -m scripts.create_admin --email <existing>` on
   the host to promote/reset that account; it is server-side only by design.
3. **Leaked API key** → rotate it in the secret store, redeploy; the platform has no
   key material in the database.
4. **Deploy pipeline misbehaving** → set `PIPELINE_MODE=simulated` immediately; the
   flow becomes a labelled dry run instead of touching real repositories.
