# A.R.M.X AI

A Claude-powered assistant platform shipped as a **web app** and a **native app**
(Android + desktop + Wear OS companion), sharing one FastAPI backend, plus an
auto-build-and-deploy pipeline that turns a sentence into a live site — with a
human confirming every consequential step.

The guiding rule of the whole codebase: **the model is an untrusted planner.**
It can request a registered tool by name with schema-validated arguments. Only the
Security Gateway authorises and executes it, and every medium- or high-risk action
waits for a single-use approval bound to a hash of the exact action.

```
Web app (Next.js)  ─┐
Native app (Flutter)─┴─▶ FastAPI core ─┬─▶ LLM adapters (Claude | OpenAI | offline)
                                       ├─▶ Security Gateway ─▶ Tool Registry (21 tools)
                                       ├─▶ Build & deploy pipeline (GitHub ▸ Vercel ▸ Turso)
                                       ├─▶ Integrations (Home Assistant, IMAP, search,
                                       │                 WhatsApp/Messenger, device link)
                                       └─▶ Postgres/SQLite + Redis + hash-chained audit
```

---

## Quick start (one command, no Docker)

Requirements: Python 3.11+, Node 20+.

```bash
cp .env.example .env         # optional: the defaults run offline
make install                 # creates backend/.venv, installs Python + npm deps
make dev                     # api on :8000, web on :3000
```

Then open <http://localhost:3000>, sign up, and talk to the assistant.

That works immediately because a **deterministic offline planner** is used when no
`ANTHROPIC_API_KEY` is set: it routes your request to real tools through the real
gateway and the real UI, and every reply says so. Add a key and set
`LLM_PROVIDER=claude` to hand planning to Claude — nothing else changes.

### Check it end to end in 60 seconds

```bash
make test                    # 68 backend tests (auth, gateway, devices, pipeline, hardening)

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

```bash
make admin                                     # prompts for email + password
# or: cd backend && .venv/bin/python -m scripts.create_admin --email you@example.com
```

### Docker (production shape)

```bash
cp .env.example .env
# edit .env: POSTGRES_PASSWORD, JWT_SECRET, WEB_ORIGIN, ANTHROPIC_API_KEY...
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec api python -m scripts.create_admin
```

Stack: nginx (rate limiting, security headers) → web + api → Postgres + Redis, plus
a worker for approval expiry and scheduled automations. Migrations run on boot
(`AUTO_CREATE_TABLES=false`; the app refuses to start in production otherwise).

---

## What is real, what needs a key

| Capability | Default state | To go live |
|---|---|---|
| Chat / planning | offline planner (labelled) | `LLM_PROVIDER=claude` + `ANTHROPIC_API_KEY` |
| Tool authorisation, approvals, audit | **fully live** | — |
| Auth (argon2, rotating refresh, reset, Google OIDC) | **fully live** | SMTP for real reset mail; `GOOGLE_*` for OIDC |
| Site generation + design lint + preview | **fully live** | — |
| Deploy (GitHub + Vercel + Turso) | simulated, clearly flagged | `PIPELINE_MODE=live` + tokens + allowlist |
| Smart home | reports "not configured" honestly | `HOME_ASSISTANT_URL/TOKEN` |
| Web search | reports "not configured" | `SEARCH_PROVIDER` + key |
| Read-only mail | reports "not configured" | `IMAP_*` |
| WhatsApp / Messenger | simulated | `MESSAGING_MODE=live` + tokens |
| Linked devices, calls, app launch | **API + native client live**; execution happens on the device | pair a device |
| Native app (Flutter) | complete source in `app/` | `flutter pub get && flutter run` |

Nothing silently pretends to work: every unavailable integration returns a
structured "not configured" payload that the UI renders, and every simulated
response carries `simulated: true`.

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
  tests/            68 tests: auth, gateway, injection, devices, builder, hardening
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
make worker         # background worker
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
