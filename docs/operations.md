# Operations: deploy, backup, restore, monitoring

## Staged deployment

1. **Local** — `make install && make dev && make test`.
2. **Staging** — use a separate Turso database and `LLM_PROVIDER=mock` so planner
   tests cost nothing. Walk the checklist below.
3. **Production** — `ENV=production`, real keys and the production Turso database.
   The app refuses to boot with placeholder secrets, without Turso, with
   `AUTO_CREATE_TABLES=true`, or when `WEB_ORIGIN` is not HTTPS.

### Pre-flight checklist

- [ ] `JWT_SECRET` is ≥ 32 random bytes (`openssl rand -base64 48`)
- [ ] `TURSO_DATABASE_URL` and database auth `TURSO_AUTH_TOKEN` are paired
- [ ] `LLM_SECRETS_KEY` is a stable Fernet key and has a separately secured copy
- [ ] `GROQ_API_KEY` is set; preferred model is configurable with `GROQ_MODEL`
- [ ] Either the `FIRST_ADMIN_*` pair or `INITIAL_SETUP_TOKEN` is set for first boot
- [ ] SMTP configured (password reset fails closed without it in production)
- [ ] `WEB_ORIGIN` / `CORS_ORIGINS` are the real HTTPS origin
- [ ] `GITHUB_ALLOWED_TARGETS` (or `GITHUB_DEFAULT_ORG`) set before `PIPELINE_MODE=live`
- [ ] `alembic upgrade head` has run (the image entrypoint does it on boot)
- [ ] First owner can log in; bootstrap password/token has been removed from Render
- [ ] Admin → Models shows a healthy Groq route and configured failover routes
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

Nginx serves the web app and `/api/*` on one origin. FastAPI and Next.js bind only
to container loopback. Housekeeping and scheduled automations run as a task inside
the API lifespan so a Turso embedded replica has exactly one process owner. Ports
`3000` and `8000` are internal. Do not override the image command with `next start`
or `uvicorn`: that omits services and the proxy. The entrypoint renders nginx,
validates configuration, runs `alembic upgrade head`, then starts Supervisor. A
failed migration or initial Turso synchronization stops startup.

### Required environment

- `ENV=production` (the image default), `DEBUG=false`, and
  `AUTO_CREATE_TABLES=false`. Do not weaken these guards to make a deploy pass.
- `JWT_SECRET`: a long random secret, generated with `openssl rand -base64 48`.
  Keep it stable across restarts; there is no insecure production fallback.
- `WEB_ORIGIN`: the actual public HTTPS origin. On Render only, unset values are
  derived from `RENDER_EXTERNAL_URL`. An explicit value always wins.
- `CORS_ORIGINS`: defaults to `WEB_ORIGIN` in the root entrypoint when unset.
- `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`: the application database and its
  database auth token. Production requires both and ignores `DATABASE_URL` when
  they are present.
- `TURSO_REPLICA_PATH=/data/turso-replica.db`: local embedded replica. Keep one
  Render instance attached to this path. Startup pushes pending local operations,
  pulls remote changes, and refuses to become healthy when initial sync fails.
- `LLM_SECRETS_KEY`: stable Fernet key used only for encrypted provider credentials.
  Rotating it requires re-entering every admin-managed provider key.
- `GROQ_API_KEY`: seeds Groq as priority 10 with configurable `GROQ_MODEL`.
  `OPENAI_API_KEY` and Anthropic keys seed priority-20 fallbacks; all other public
  OpenAI-compatible HTTPS providers are added in Admin → Models.
- `FIRST_ADMIN_EMAIL` + `FIRST_ADMIN_PASSWORD`, or `INITIAL_SETUP_TOKEN`: choose one
  first-run bootstrap. Neither path overwrites an existing administrator.

Mount `/data` and ensure it is writable by UID `10001`. Turso is authoritative,
but the disk avoids a full replica bootstrap and preserves `/data/workspace` and
`/data/media` across deploys. Do not run multiple Render instances against one
replica file. The API retries pending pushes before each periodic pull; an API
request whose remote push fails returns an error even though its local transaction
may be durable, so clients should re-read state before retrying a non-idempotent
operation.

Redis is deliberately not required for this single-instance Render topology.
`REDIS_URL` is reserved for a future shared rate-limiter if horizontal HTTP
scaling is introduced. Allow at least the image's 60-second health-check startup
period because migrations, Turso bootstrap and the Python/Node services take
longer than a static site.

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

Enable Turso backups/point-in-time recovery for the production database and keep
a separately protected logical export. With the Turso CLI authenticated:

```bash
mkdir -p backups
turso db shell YOUR_DATABASE ".dump" > "backups/armx-$(date +%F).sql"
curl -fsS -H "Authorization: Bearer $ADMIN_TOKEN" \
  "https://armx.example/api/admin/audit?limit=200000" \
  > "backups/audit-$(date +%F).json"
```

Restore the SQL into a **new** Turso database, point a staging deployment at it,
and never test restoration against production. Generated project files are also
stored in `generated_projects.files`; media in `/data/media` must be copied with
the same cadence.

**Restore drill (run quarterly):** restore to a scratch Turso database, use a fresh
replica path, sign in, verify `/api/admin/audit/verify` returns `ok: true`, open a
conversation, generate a site, test one provider route, then destroy the scratch
deployment.

## Monitoring and alerting

| Signal | Source | Alert |
|---|---|---|
| API liveness | `GET /api/health` | 2 consecutive failures → page |
| Planner errors | audit `assistant.error` | > 5/min → warn (key or quota issue) |
| Model pool | `GET /api/assistant/provider` | healthy routes = 0 or circuit-open spike → alert |
| Turso sync | application logs containing `Turso sync failed` | any sustained failure → page; do not redeploy over pending writes |
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
