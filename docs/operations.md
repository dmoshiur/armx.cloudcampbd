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
