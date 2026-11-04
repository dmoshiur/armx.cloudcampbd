# A.R.M.X AI — full repository audit (2026-11-03)

Scope: architecture, configuration, backend/auth/AI/tools/database, all web app
routes, deployment files, tests and documentation at `84368ff` (227 tracked
files). Static review covered the file inventory and the critical paths in
detail; the Flutter/Android native sources were inventoried but not built in
this environment. Dependency install, the complete backend test suite and a
production web build were run locally. Render service logs, browser traces and
the production database are **not** reachable here; statements about those are
marked "deployment-dependent".

## 1. What actually exists

| Area | Implementation | State |
|---|---|---|
| Web frontend | `web/` — Next.js 15 App Router, Tailwind, TanStack Query, Zustand dependency (unused), typed `/api` client with rotating refresh tokens | Builds clean; 6 app routes |
| Native client | `app/` — Flutter/Dart sources + Android/Kotlin device-owner, consent, voice and telemetry services | Source complete; no runner binaries built here |
| API | `backend/` — FastAPI, SQLAlchemy 2 async, Alembic, Pydantic settings, argon2id, JWT + rotating refresh sessions, Google OIDC, rate limiting | 90/90 tests pass |
| Database | SQLite (dev) / Turso embedded replica (prod) with hash-chained `audit_events`, users, sessions, devices, approvals, LLM routes, projects, conversations, messages, chat runs | 3 migrations; prod uses `alembic upgrade head` |
| AI | `app/llm/` — DB-backed weighted router with circuit breaker, OpenAI-compatible (Groq/OpenAI), Anthropic, deterministic offline planner; encrypted API keys; SSRF check on custom base URLs | Non-streaming only |
| Tools | 21 tools in `app/tools/`, Pydantic input schemas, risk tiers, gateway preflight, single-use approvals bound to tool+args+actor+session+expiry, audit trail | Real execution for local integrations; external ones report "not configured" |
| Builder | `app/builder/` sandbox generator + design lint + signed preview; GitHub/Vercel/Turso integration behind `PIPELINE_MODE` | `simulated` mode reports fabricated `READY` URLs (fixed in this upgrade) |
| Devices | linked-device pairing, command queue, policies, consent sessions, mirror frames, device-owner Android client | Live API; host execution is device-side |
| Deploy | root `Dockerfile` (nginx → Next.js/FastAPI, Alembic on boot), `render.yaml` Blueprint, compose stack, health check | Single Render instance with `/data` disk |

> The table above describes the baseline commit `84368ff`, not the finished
> upgrade. Post-implementation verification is recorded in section 4 and in
> `docs/ENGINEERING_CHECKLIST.md`.

### Navigation → implementation map (before this upgrade)

| Nav item | Backing endpoint | Verdict |
|---|---|---|
| Assistant | `POST /api/assistant/chat`, `GET /api/assistant/conversations` | Real |
| Site builder | `/api/projects`, `/api/preview/...`, `web_generate` tool | Real preview; deploy was simulated but labelled |
| Devices | `/api/devices`, `/api/devices/{id}/management/...` | Real |
| Capabilities | `/api/tools`, `/api/integrations` | Real |
| Settings | `/api/auth/me`, `/api/integrations`, local theme | Partly local-only (theme in `localStorage`, `users.theme` unused) |
| Admin | `/api/admin/*`, `/api/admin/llm/*` | Real, server-side `require_admin` |
| Conversations, Projects, Tool Registry, Automations, Memory, Activity Logs | — | Missing as first-class pages; data partly existed in DB (`automation_rules`, `audit_events`) |

## 2. Root causes of the reported failures

### 2.1 "Something went wrong — Request failed"

`web/components/ui/primitives.tsx` supplies the title; the message came from
`web/lib/api/client.ts`:

```ts
messageFrom(payload, res.statusText || "Request failed")
```

When a proxy error, 502/504, empty body or non-JSON response arrived there was no
`detail`, so the user saw the literal string `"Request failed"` with no reason,
request ID or recovery action. `fetch()` network exceptions were flattened into
"Could not reach the assistant" without status, correlation ID or a retry that
replays the actual message. The backend already emitted `X-Request-ID`, but the
client only surfaced it for `ApiError` objects created from a parsed response.
**Fix:** structured, classified errors everywhere (see `app/core/errors.py`),
correlation IDs in every error, actionable hints, retry that keeps the draft,
and no generic fallback strings.

### 2.2 AI route / model confusion

* `render.yaml` and `.env.example` hard-code `GROQ_MODEL=llama-3.3-70b-versatile`,
  while the deployed dashboard shows `openai/gpt-oss-120b`. The DB `llm_models`
  table is authoritative and `seed_environment_providers()` upserts environment
  routes, so an operator-added model can legitimately be the active route. The UI
  displayed `provider` only, never `model`, and `/api/assistant/chat` returned
  `provider` but not the exact model used for that turn. Nothing exposed the
  failover path or token usage.
* `RoutingAdapter.complete()` silently fell back to `MockAdapter` after all live
  routes failed. The reply was labelled, but the HTTP 200 response did not carry an
  explicit `fallback` reason.
* No provider-level retry/backoff for 429/5xx (only failover to the next route), no
  request log, no `context window exceeded` / `invalid credentials` classification.

**Fix:** exact `provider`/`model`/`fallback`/`usage` on every outcome, persisted
`llm_request_logs`, retry with exponential backoff on retryable statuses,
classified errors, and a provider-health endpoint.

### 2.3 "Approval request expired or dismissed — ask again to retry the action."

The frontend renders that exact string whenever `turn.approval` is set but the local
`approval` state has been cleared. Root causes:

1. `APPROVAL_TTL_SECONDS=120` and approvals are bound to `session_id`. Refresh-token
   rotation creates a new `Session`, so a pending approval can no longer be consumed
   (`approval_wrong_session`).
2. `GET /api/assistant/approvals` existed but the web app **never called it**: a page
   refresh discarded the in-memory approval and there was no way to resume.
3. The worker marks `approvals.status='expired'` but never updates the `ChatRun`, so
   the run stays `awaiting_approval` forever with no retry path.
4. `resume_run()` trusts `run.paused_call_json` but there was no endpoint to mint a
   *new* approval for the same paused call; the only advice was "ask again".

**Fix:** approval restore on load, explicit statuses, `POST /runs/{id}/retry` that
marks the old record expired and issues a fresh approval bound to the current
session, duplicate-execution protection, and structured `approval_expired` errors
with `can_retry`.

### 2.4 Persistence gaps

`Conversation` had only `user_id` + `title` + timestamps; `Message` had only role,
content, tool calls and created_at. There was no archive/pin/model/token usage/
project association, no rename, search, pagination, export, summary, edit/resend,
regenerate, feedback or message status. Conversations did survive refresh (they
are in the DB), but the UI offered no durable management. Long-term memory did not
exist at all. `users.theme` was never used; theme lived only in `localStorage`.

### 2.5 Composer and chat UX

The composer was inside a normal document-flow `<section>` with
`min-h-[calc(100vh-150px)]`, not fixed to the viewport. On mobile the bottom nav
(`fixed ... bottom-0`) overlapped it. Messages were rendered with
`whitespace-pre-wrap` only — no Markdown, code highlighting, copy, timestamps,
search, regenerate, edit, stop, feedback or attachments. There was no streaming
transport: the browser waited for the whole 50-second pipeline.

### 2.6 Background

The app used the npm `cmatrix@0.5.3` package (jcubic/cmatrix, MIT, a faithful
JavaScript port of the terminal effect) — *not* a CSS imitation, but also not the
original GPL-3.0 `abishekvashok/cmatrix` executable. It had no settings panel,
no status indicator, no enable switch, no speed/density/opacity control and no
way to know which implementation was actually running.

Audit of the reference project: `abishekvashok/cmatrix` is **GPL-3.0**
(`COPYING`), written in C, requires **ncurses** and a real terminal. Its `-u`
(delay), `-C` (colour), `-a` (asynchronous scroll) and `-b` (bold) flags control
the authentic falling streams. Running it requires a PTY; a canvas is not enough
to claim the executable ran.

### 2.7 Other findings

* `deploy/runtime/nginx.conf` had no `Upgrade`/`Connection` forwarding on
  `location /api/`, so a backend WebSocket could never connect in production.
* `github_vercel.deploy_project()` in `PIPELINE_MODE=simulated` returned
  `ok=True, status="READY", url="https://....vercel.app"` with no provider call;
  `web_deploy` then wrote `project.status="deployed"` and `vercel_url`. Honest
  labelling existed in chat text, but the persisted project record claimed success.
* `/api/media/upload` accepted images only; the composer had no upload UI at all.
* `AutomationRule` existed but had no CRUD API and the worker only handled
  `time:HH:MM` + `alarm`.
* `ToolSpec` had an input schema but no declared output schema, timeout or explicit
  permission list other than `scopes`.
* `GET /api/health` checked `SELECT 1` but no provider/db-migration/error summary.
* `web/next.config.mjs` rewrites `/api/*` to `BACKEND_URL`; SSE works through this
  path but WebSocket upgrades are dev-server dependent.
* No secrets are present in the repository or frontend bundles. API keys live in
  env vars or encrypted DB rows (`LLMProvider.api_key_encrypted`).
* Duplicated/dead code: `app/llm/factory.py` builds an environment-only adapter
  retained for isolated components; `app/models/user.py` exports `Text` and an
  unused `CreatedByMixin`; `web/package.json` includes `zustand` with no imports.
  Preserved to avoid gratuitous churn; documented rather than deleted.

## 3. Prioritised engineering checklist

Priority 1 (correctness / trust): error classification & correlation IDs, approval
restore/retry/session binding, honest deployment status, exact model reporting,
persistent conversations & memory migration, streaming + stop, secure composer.

Priority 2 (product): responsive navigation, fixed composer, chat operations
(markdown/code/copy/edit/regenerate/feedback/search), 12 real navigation
destinations, DB-backed preferences and Matrix settings.

Priority 3 (infrastructure): real CMatrix binary in an isolated PTY with
authenticated WebSocket/SSE frame streaming, MIT-licensed fallback with honest
status, nginx upgrade forwarding, provider health/usage/log endpoints, tests.

See `docs/ENGINEERING_CHECKLIST.md` for the live status of each item.

## 4. Post-implementation audit and verification (2026-11-04)

The upgrade kept the existing FastAPI app factory, Argon2id password hashes,
JWT/session records, RBAC roles, admin bootstrap and Turso/Alembic architecture.
Authentication now uses HttpOnly `SameSite=Lax` cookies as the browser source of
truth, while legacy bearer tokens remain accepted for existing API clients.
Double-submit CSRF applies to ambient cookie sessions; explicit bearer and paired
device credentials are not treated as cookie sessions. An invalid bearer token
never silently falls back to a valid cookie.

### 4.1 Resend-only transactional email

The old SMTP/outbox mailer was replaced with the official Resend REST API using
the existing `httpx` dependency. No `smtplib`, SMTP credential or SMTP port is
used. `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `APP_BASE_URL` and the optional
`RESEND_WEBHOOK_SECRET` are server-side only. Root and backend `.env.example`
files, `render.yaml`, `docs/RESEND_SETUP.md` and `/api/config` were updated.

Recovery and verification links are absolute HTTPS URLs in production, with
15-minute and 24-hour expiries respectively. Only SHA-256-style token hashes,
consumption timestamps and delivery metadata are stored. A 60-second cooldown
and stable idempotency key prevent duplicate sends; only 429/5xx responses are
retried, with bounded exponential backoff. A 2xx API response is recorded as
`accepted`, never `delivered`. Signed Resend/Svix events advance the durable
`EmailDelivery` ledger to `sent`, `delivered`, `delayed`, `bounced`,
`complained` or `failed`; replayed/forged events are rejected and deduplicated.
Admin-only `/api/admin/email-deliveries` and Settings → System expose the ledger
without keys or raw links.

Without credentials in development, the local outbox records an explicit
`not_configured` link and the ledger says `not_configured`; no real email is
claimed. Production startup refuses missing/placeholder Resend values and a
non-HTTPS `APP_BASE_URL`/`WEB_ORIGIN`.

### 4.2 Frontend and deployment integrity

The 12-item shell now points to real pages: conversations, projects,
capabilities, tools, automations, memory, activity and settings are implemented
against server APIs. The assistant uses durable SSE, structured errors with
request IDs, approval cards, conversation CRUD, DB preferences and exact model
routes. The builder generates real files, edits them, snapshots/restores versions,
downloads a ZIP, shows a signed sandboxed iframe and only displays a live URL
after provider confirmation. `render.yaml` uses `PIPELINE_MODE=live`; missing
provider credentials produce an honest `not_configured` status.

The original GPL-3.0 CMatrix executable is streamed via an isolated PTY over
authenticated WebSocket/SSE when installed. The vendored MIT JavaScript port is
labelled as a fallback. In this sandbox the executable was missing: status, SSE
and WS all reported that honestly instead of claiming the binary ran.

### 4.3 Tests and limits

- Backend: `100 passed in 33.31s`, including 10 new Resend/cookie/CSRF/webhook
  tests and the existing 90-test suite.
- Frontend: TypeScript check clean; Next 15.5.28 production build generated
  `23/23` static pages.
- Migrations: fresh `upgrade head → downgrade b7e41c9d2a10 → upgrade head`
  succeeded through `c9f2a1d34e77`.
- Live local HTTP: all listed app/auth pages returned `200`; cookie/CSRF
  enforcement, Matrix SSE/WS honesty, unconfigured webhook `503`, admin ledger
  `401` and `/api` proxy responses were verified.
- Frontend bundle: no secret values; only non-secret variable names appear in
  explanatory UI copy.
- `nginx -t`, `docker build`, a real CMatrix PTY, live Resend email/webhook,
  Flutter/Android builds, browser console/network/overflow and a visual
  comparison against the Postimages login reference remain unverified because
  the binaries, credentials, browser tooling and reference image were not
  available. The Postimages HTML was reachable but its image endpoints failed.
  These items are explicitly recorded in `docs/ENGINEERING_CHECKLIST.md` and are
  not marked complete.
