# A.R.M.X AI

A multi-provider assistant platform shipped as a **web app** and a **native app**
(Android + desktop + Wear OS companion), sharing one FastAPI backend, plus an
auto-build-and-deploy pipeline that turns a sentence into a live site — with a
human confirming every consequential step.

The guiding rule of the whole codebase: **the model is an untrusted planner.**
It can request a registered tool by name with schema-validated arguments. Only the
Security Gateway authorises and executes it, and every medium- or high-risk action
waits for a single-use approval bound to a hash of the exact action.

```
Web app (Next.js)  ─┐
Native app (Flutter)─┴─▶ FastAPI core ─┬─▶ weighted LLM router (Groq | compatible APIs | Anthropic)
                                       ├─▶ Security Gateway ─▶ Tool Registry (21 tools)
                                       ├─▶ Build & deploy pipeline (GitHub ▸ Vercel ▸ Turso)
                                       ├─▶ Integrations (Home Assistant, IMAP, search,
                                       │                 WhatsApp/Messenger, device link)
                                       └─▶ Turso embedded replica + hash-chained audit
```

---

## Quick start (one command, no Docker)

Requirements: Python 3.11+, Node 20+.

```bash
make install                 # creates backend/.env with offline development defaults
make dev                     # api on :8000, web on :3000
```

The root `.env.example` is the Render production template. Local development uses
`backend/.env.example`, copied automatically by `make install`.

```bash
# optional: inspect or edit local defaults
$EDITOR backend/.env
# then start both services
make dev                     # api on :8000, web on :3000
```

Then open <http://localhost:3000>, sign up, and talk to the assistant.

That works immediately because a **deterministic offline planner** is used when no
live route is configured: it routes your request to real tools through the real
gateway and the real UI, and every reply says so. Render defaults to Groq with
`llama-3.3-70b-versatile`; additional compatible or Anthropic models can be
weighted, tested, enabled and failed over from the admin panel.

### Check it end to end in 60 seconds

```bash
make test                    # backend tests (auth, routing, gateway, devices, pipeline, hardening)

# 1. Sign up through the UI, then in the chat: "build a landing page for a bakery in Dhaka"
#    → the assistant drafts the site, runs the design lint, renders a preview
#    → a confirm dialog names the exact tool, risk tier and arguments
# 2. Approve → preview appears inline. Then say "deploy it".
#    → a second, HIGH-risk dialog names the GitHub repo and Vercel project
# 3. Approve → the project list shows the repo, deployment and (optional) Turso DB
```

Deployments run in `PIPELINE_MODE=simulated` by default, clearly labelled in both
the UI and the API response. Set `PIPELINE_MODE=live` plus the GitHub/Vercel
tokens to create real repositories and deployments.

### Create the first admin (never through public signup)

For Render, choose one protected bootstrap in the root `.env.example`:

1. Set `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` for the first deploy, then
   remove the password after login; or
2. Set a random `INITIAL_SETUP_TOKEN`, open `/setup` once, then remove the token.

Setup closes permanently when an administrator exists. Local operators can also run:

```bash
make admin
# or: cd backend && .venv/bin/python -m scripts.create_admin --email you@example.com
```

### Docker (production shape)

```bash
cp .env.example .env
# fill the blank Turso, JWT, LLM encryption, Groq and bootstrap values
docker compose -f deploy/docker-compose.yml up -d --build
```

Stack: nginx (rate limiting and security headers) → web + API → Turso. Redis is
not required. Housekeeping runs in the API lifecycle, and migrations run on boot
(`AUTO_CREATE_TABLES=false`; the app refuses to start in production otherwise).

### Single-container deployment (root Dockerfile)

For Render, apply `render.yaml` as a Blueprint (it creates the `/data` disk and
health check), or create a Web Service from this repository using `Dockerfile`
with build context `.`. Copy the root `.env.example` names into Render and fill
the blank secret/Turso/Groq/bootstrap values. The image packages Next.js, FastAPI and
a rootless nginx proxy; housekeeping runs inside the API process so the Turso
embedded replica has one process owner. Only nginx is public on runtime `PORT`
(default `10000`). Alembic migrations run before services start.

```bash
docker build -t armx .
docker volume create armx-data
docker run --rm -p 10000:10000 \
  -v armx-data:/data \
  -e ENV=production \
  -e JWT_SECRET="$(openssl rand -base64 48)" \
  -e LLM_SECRETS_KEY="YOUR_FERNET_KEY" \
  -e TURSO_DATABASE_URL="libsql://YOUR_DATABASE.turso.io" \
  -e TURSO_AUTH_TOKEN="YOUR_DATABASE_TOKEN" \
  -e GROQ_API_KEY="YOUR_GROQ_KEY" \
  -e FIRST_ADMIN_EMAIL="owner@example.com" \
  -e FIRST_ADMIN_PASSWORD="A_LONG_RANDOM_INITIAL_PASSWORD" \
  -e WEB_ORIGIN=https://your-app.example \
  armx
```

For a public deployment, replace `WEB_ORIGIN` with the actual HTTPS origin and
publish the mapped port through your host's TLS proxy. The example above is for
running behind an existing HTTPS proxy, not for exposing plain HTTP to users.
On Render, `RENDER_EXTERNAL_URL` supplies `WEB_ORIGIN` and `CORS_ORIGINS` when they
are blank. Set the health check path to `/api/health` and mount a persistent disk
at `/data`; Turso remains the authority, while the disk preserves the embedded
replica and generated project artifacts across restarts. Redis is not required
for this single-instance deployment. Keep exactly one Render instance attached
to a replica path. See [operations](docs/operations.md#single-container-hosts-eg-render)
for secret rotation, backups and restore checks.

---

## What is real, what needs a key

| Capability | Default state | To go live |
|---|---|---|
| Chat / planning | offline planner (labelled) | `GROQ_API_KEY` + `LLM_SECRETS_KEY`; add/fail over routes in Admin → Models |
| Tool authorisation, approvals, audit | **fully live** | — |
| Auth (argon2, rotating refresh, reset, Google OIDC) | **fully live** | SMTP for real reset mail; `GOOGLE_*` for OIDC |
| Site generation + design lint + preview | **fully live** | — |
| Deploy (GitHub + Vercel + Turso) | simulated, clearly flagged | `PIPELINE_MODE=live` + tokens + allowlist |
| Smart home | reports "not configured" honestly | `HOME_ASSISTANT_URL/TOKEN` |
| Web search | reports "not configured" | `SEARCH_PROVIDER` + key |
| Read-only mail | reports "not configured" | `IMAP_*` |
| WhatsApp / Messenger outbound | simulated | `MESSAGING_MODE=live` + access tokens |
| WhatsApp inbound webhook | signature-verified endpoint, auto-reply disabled | separate `WHATSAPP_VERIFY_TOKEN` + `WHATSAPP_APP_SECRET` |
| Linked devices, calls, app launch | **API + Android client foundation live**; host execution remains platform-specific | pair a device |
| Native app (Flutter) | Android source in `app/`; desktop runners are a staged release target | `flutter pub get && flutter run` |

The web background uses the MIT-licensed `cmatrix` browser canvas package rather
than a CSS imitation. Continuous animation is disabled when the operating system
requests reduced motion.

Nothing silently pretends to work: configured LLM routes are shown as
**unverified** until a real completion succeeds, failed routes are degraded and
use the labelled offline fallback, and every API error includes an `X-Request-ID`
that can be matched to server logs. Provider attempts and the complete failover
path have independent deadlines, so a dead provider cannot leave chat waiting
indefinitely. Every unavailable integration returns a structured "not configured"
payload, and every simulated response carries `simulated: true`.

### WhatsApp webhook setup

Use `https://YOUR_RENDER_HOST/api/webhooks/whatsapp` as Meta's callback URL.
`WHATSAPP_TOKEN` is the outbound Graph API access token; it is **not** accepted as
the verification token. Generate a different random `WHATSAPP_VERIFY_TOKEN`, and
set `WHATSAPP_APP_SECRET` to the app secret from Meta. GET subscription challenges
use the verification token, while every POST is authenticated against the exact
raw request body with `X-Hub-Signature-256`. Signed events are acknowledged but
are not allowed to execute tools or auto-reply until a contact is explicitly
mapped to a tenant.

---

## Repository layout

```
backend/            FastAPI core
  app/core/         config (typed, production-guarded), security, db, media, mailer
  app/models/       SQLAlchemy models (users, devices, approvals, audit, projects…)
  app/api/          auth, assistant, devices, admin, platform routes
  app/llm/          provider-agnostic adapter: claude | openai | mock
  app/registry/     the plugin system every capability registers into
  app/security/     Security Gateway, risk tiers, approvals, tickets
  app/audit/        append-only hash-chained audit writer + verifier
  app/tools/        one file per tool (21 of them)
  app/integrations/ home_assistant, github_vercel, turso, search, mail, messaging, telecom
  app/builder/      sandbox generator, design lint, signed previews
  alembic/          migrations (initial schema committed)
  tests/            90 tests: auth, routing, webhooks, gateway, devices, builder, hardening
web/                Next.js 15 + Tailwind (App Router)
  components/ui/    the shared component library
  lib/api/          typed client with rotating-token refresh
  app/(app)/        assistant, builder, devices, capabilities, settings, admin
  app/(auth)/       login, signup, reset, verify
app/                Flutter (Android, desktop, Wear OS companion)
  lib/core/         theme (same tokens), breakpoints, router/shell, api client
  lib/features/     auth, assistant, smart_home, devices, alarms, guest_greeter,
                    web_builder, messaging, settings, admin, voice, device_bridge
design/tokens.json  single source of truth for colour, type, spacing, layout
deploy/             docker-compose.yml, nginx.conf
docs/               architecture, threat model, risk matrix, operations, phases
examples/           Home Assistant config + ESP32 firmware for the smart-home demo
```

---

## Security model in one screen

* The LLM **cannot execute anything**; it emits tool requests. The gateway is the
  only path to a handler.
* Every medium/high action needs an approval bound to `sha256(tool + args + actor +
  session + expiry)`. Change one argument → the approval is invalid. Each is single-use.
* The kill-switch halts all integrations instantly, independent of the AI.
* Per-user and global tool toggles are enforced in the gateway, not the UI.
* Deploy destinations are allowlisted; the model cannot invent a repo or project.
* Tool output is wrapped and labelled as untrusted data; injection in a web page,
  email or search result cannot turn into an action.
* Argon2id passwords, hashed refresh tokens with rotation + reuse detection,
  hashed reset/pairing tokens, lockout, rate limits, security headers.
* Linked devices: pairing happens on the device, unlink needs the owner's device
  password (no admin override endpoint), the link is always visible, and screen
  sharing is a flagged session either side can end.
* The audit log is append-only and hash-chained; `/api/admin/audit/verify` reports
  the first tampered index.

Full detail: [docs/architecture.md](docs/architecture.md),
[docs/threat-model.md](docs/threat-model.md),
[docs/risk-matrix.md](docs/risk-matrix.md).

---

## Commands

```bash
make install        # install backend + web dependencies
make dev            # run api (:8000) and web (:3000) together
make api            # api only
make web            # web only
make test           # backend test suite
make lint           # ruff + tsc
make migrate        # alembic upgrade head
make admin          # create the first admin
make clean          # remove build artefacts and local databases
```

## Account roles

| Role | Can do |
|---|---|
| `user` | chat, generate/deploy sites, smart home, search, mail |
| `vip` | everything above **+ link and manage their own named devices** |
| `admin` | everything + user management, tool toggles, audit log, kill-switch; device view is **read-only** |

Public signup always creates a `user`. The first admin comes from the CLI script.

## Design system

One Tailwind set, one Flutter theme, both generated from `design/tokens.json`:
ink `#0B1220`, navy `#101935`, accent `#5B8CFF`, accent2 `#8B5CF6`, fog `#F4F6FB`,
line `#D7DCEA`, muted `#5B6475`. Dark by default, light swaps surfaces and keeps
accents. Breakpoints compact <600 / medium 600-1024 / expanded ≥1024, content
capped at 1200px, 48dp+ touch targets, and every data screen has loading, empty and
error states. The deploy pipeline runs the same rules as a lint gate before shipping.
