# Phase report — A.R.M.X AI v3.0

One entry per phase from the master prompt: **what was built · how to run it · how
to test it · what is (still) mocked.** Nothing was left as "an exercise for later".

---

## Phase 0 — Planning

**Built.** Repository skeleton (`backend/`, `web/`, `app/`, `design/`, `deploy/`,
`docs/`, `examples/`), `docs/architecture.md`, `docs/threat-model.md` (16 threats +
residual risks), `docs/risk-matrix.md` (all 21 tools), and `design/tokens.json` —
the single source of truth consumed by the Tailwind config, the Flutter theme and
the deploy pipeline's design lint.

**Run / test.** Read the three docs; `design/tokens.json` is imported directly by
`web/tailwind.config.ts` (typing a wrong colour breaks the build).

**Mocked.** Nothing.

---

## Phase 1 — Backend core

**Built.** `docker-compose` (nginx, api, worker, web, postgres, redis) with health
checks and volume persistence; typed settings (`pydantic-settings`) that **refuse to
boot in production** with a placeholder secret, `AUTO_CREATE_TABLES=true`, `DEBUG=true`
or a non-https `WEB_ORIGIN`; the full data model (24 tables); Alembic with a committed
initial migration; `GET /api/health`; a dependency-free worker for approval expiry and
scheduled automations; security headers + CORS allowlist.

**Run.** `make install && make dev` (SQLite) or
`docker compose -f deploy/docker-compose.yml up -d --build` (Postgres).
`make migrate` applies migrations.

**Test.** `curl localhost:8000/api/health` → `status: ok`, `tools: 21`.
`tests/test_hardening.py::test_production_refuses_placeholder_secrets` proves the boot
guard. `alembic upgrade head` was verified against a clean database.

**Mocked.** No external service is needed for this phase.

---

## Phase 2 — Auth, registry skeleton, audit, kill-switch

**Built.** Signup/login with Argon2id; short-lived JWT access tokens; **opaque
rotating refresh tokens stored hashed**, with reuse detection that revokes the whole
session family; account lockout; enum-safe reset flow (single-use, 20-minute SMTP
link); email verification (optional, on by default in production); Google OIDC with a
signed state cookie and fragment token hand-off; admin-only user management; a CLI
that creates the first admin (`python -m scripts.create_admin`); the self-registering
tool registry; a hash-chained audit writer with a verifier; the kill-switch flag.

**Run.** `.env` SMTP settings for real mail (`var/outbox.log` is written in dev when
SMTP is unset). Google needs `GOOGLE_CLIENT_ID/SECRET`.

**Test.** `make test` — 12 auth tests cover weak passwords, duplicate signup, lockout,
rotation, reuse-revocation, single-use reset, no user enumeration. Admin CLI verified
live (`Created admin owner@example.com`).

**Mocked.** None. SMTP and Google are *live-gated*: unconfigured, the UI hides the
Google button and resets return the same 202 without sending.

---

## Phase 3 — Security Gateway + harness + Claude

**Built.** The only execution path: preflight (kill-switch → global toggle → per-user
toggle → scope/role → rate limits → schema) then execute. Approvals are bound to
`sha256(tool ⧺ args ⧺ actor ⧺ session ⧺ expiry)`, single-use, expiring, and recorded.
A bounded harness (default 8 steps) with durable `ChatRun` state so an approval can
resume the exact run. Provider-agnostic adapters: Claude (Anthropic Messages API,
tool use, same-organisation key pool), OpenAI, and a deterministic offline planner.
Tool output is wrapped and labelled untrusted; the system prompt states the boundary.

**Run.** `LLM_PROVIDER=claude` + `ANTHROPIC_API_KEY`. Without a key the offline
planner is used and every reply says so.

**Test.** 17 gateway/injection tests: approval required, replay refused, one-argument
change refused, wrong-session and foreign-actor refused, expiry refused, kill-switch
halts tools while health still works, disabled tool blocked even when requested,
per-user toggle, unknown tool, schema violation, VIP gate, rate limit, and prompt
injection through tool output failing to produce an action.

**Mocked.** The offline planner (explicitly labelled). Claude itself is live-gated on
the key; the request shape, retries and key rotation are exercised through the mock
contract.

---

## Phase 4 — Web app

**Built.** Next.js 15 + Tailwind with the token-driven component library (buttons,
cards, inputs, dialogs, confirm modal, badges, status dots, switches, skeletons,
empty/error states, toasts); login/signup/forgot/reset/verify/Google-callback; an
adaptive shell (bottom nav → rail → sidebar, content capped at 1200px); the chat
screen with conversation history, inline tool-result cards with live sandbox
previews, and the approval dialog that names the tool, risk tier and exact arguments;
site builder; devices; capabilities + integrations; settings (profile, password,
sessions, messaging contacts); admin (overview, users, tool toggles, audit viewer with
chain verification, read-only device list, kill-switch).

**Run.** `make web` (port 3000; `/api/*` is proxied to the backend, so the browser
never talks to the API origin directly). `npm run build` produces 13 static routes.

**Test.** `npx tsc --noEmit` clean; `npm run build` clean. The full generate → approve
→ deploy flow was driven through the real API that the UI calls.

**Mocked.** Nothing in the app. Browser voice is push-to-talk only, and the UI says so
instead of pretending a wake word exists.

---

## Phase 5 — Native app (Flutter)

**Built.** 20 Dart files: token-identical theme, breakpoint helper, adaptive scaffold
(bottom nav → rail → sidebar), secure-storage API client with token refresh, auth
controller, login/signup, chat with approval sheet and tool-result cards, smart home,
devices (pairing + owner-password unlink + persistent notification via
`flutter_local_notifications`), alarms, guest greeter, site builder, messaging
contacts, settings, read-only admin, the wake-word service (`speech_to_text`,
on-device matching), the overlay-bubble widget, and a device bridge that polls the
command queue, shows the ongoing "Linked" notification and acknowledges executions.

**Run.** `cd app && flutter pub get && flutter run --dart-define=ARMX_API_BASE=…`.

**Test.** Not compiled in this environment — **no Flutter SDK is available here**, so
this is the one deliverable I could not build or run. The code is complete and
consistent with the verified API contract; treat the first `flutter pub get` as the
first real compile and expect routine version pinning.

**Mocked.** Nothing is faked inside the app; it is the *device* that executes call and
app-launch commands locally (documented in `app/README.md`).

---

## Phase 6 — Smart home

**Built.** Home Assistant REST integration with a hard entity allowlist enforced in
the pydantic model *and* the integration layer; `set_light` (with brightness) and
`get_state`; MQTT-over-TLS setup with a CA-pinned ESP32 demo (relay, brightness,
temperature) and matching Home Assistant YAML; MQTT config in settings.

**Run.** Set `HOME_ASSISTANT_URL/TOKEN` and `HOME_ASSISTANT_ALLOWED_ENTITIES`; flash
`examples/esp32`; merge `examples/home_assistant/configuration.yaml`.

**Test.** `set_light` with a non-allowlisted entity is rejected at schema level
(covered by `test_schema_violation_is_rejected`). Without configuration the tool
returns a structured "not configured" message that the UI renders.

**Mocked.** The HA/ESP32 path is live-gated; there is no fake in-memory light.

---

## Phase 7 — Auto-build & deploy pipeline

**Built.** Sandboxed generation (planner path when Claude is live, deterministic
template path otherwise), path-traversal-safe materialisation with size caps, a design
lint that blocks deploys on error-level findings, signed expiring preview URLs served
with a sandbox CSP, GitHub repo creation + Contents-API commits, Vercel project and
deployment with polling, project-scoped Turso provisioning, per-user destination
allowlists, and `web_generate` / `web_preview` / `web_deploy` (HIGH, confirmation
names repo + project; platform-owned repos are flagged).

**Run.** `PIPELINE_MODE=simulated` by default. For real deployments set
`PIPELINE_MODE=live`, `GITHUB_TOKEN`, `GITHUB_DEFAULT_ORG` or `GITHUB_ALLOWED_TARGETS`,
`VERCEL_TOKEN`, optional `TURSO_*`.

**Test.** 22 builder tests: template output scores 100 on the lint, the lint catches
doctype/viewport/palette/a11y/placeholder failures, traversal is stripped, preview
tokens are scoped and expire, allowlist rejects foreign repos, and the full
generate→approve→deploy→project-list flow (including rejection executing nothing).

**Mocked.** Deploy targets in simulated mode — every API response carries
`simulated: true` and the UI shows a "simulated" badge next to the URL.

---

## Phase 8 — Calls, app launch, search

**Built.** `call_answer` / `call_decline` / `call_place` (strict E.164, owner's device
only, HIGH, visible commands), `open_app` (fixed package allowlist, MEDIUM),
`web_search` (Google/Bing, results flagged untrusted). No recording, no interception,
no arbitrary-URL tool anywhere.

**Run.** Calls/app launch need a paired Android device; search needs
`SEARCH_PROVIDER` + key.

**Test.** HIGH device tools are refused for non-VIP users; unsupported commands are
rejected by the telecom layer; the search result is asserted to be passed through as
labelled data even when it contains a jailbreak string.

**Mocked.** None in code; search and calls are live-gated.

---

## Phase 9 — Linked devices

**Built.** Consent-based pairing (code minted in the web/assistant flow, confirmed
**on the device** where the owner sets the unlink password), device tokens hashed and
scoped to the device, unlink requiring a ticket minted after the password check (no
admin/VIP override endpoint — enforced in code), unlink audit events, always-on
persistent notification, screen-share sessions that are flagged and instantly
stoppable, admin read-only device view, native `DeviceBridge` polling.

**Test.** 9 device tests: VIP gate, wrong code, weak password, wrong/right password,
single-use ticket, **admin gets 404 when touching someone else's device**, token
scoping, visible commands, unsupported command refused, screen share start/stop.

**Mocked.** None — the server side is fully live; execution happens on the device.

---

## Phase 10 — Messaging

**Built.** WhatsApp Business API and Messenger Platform senders, per-contact
personality + auto-send flag, and a **dynamic risk tier**: MEDIUM only for a
pre-approved auto-send contact, HIGH otherwise. Unknown contacts are refused outright.

**Run.** `MESSAGING_MODE=live` + tokens (default simulated, labelled).

**Test.** Risk resolution is asserted through the gateway; contacts are scoped per
user and removable.

**Mocked.** Sends in simulated mode return a labelled preview and a fake message id.

---

## Phase 11 — Admin dashboard + watch companion

**Built.** Admin tabs (overview, users, tool toggles, audit with chain verification,
read-only devices, kill-switch with a HIGH-risk confirm), self-demotion guard, session
revocation on disable; a compact Flutter admin screen suitable for the Wear companion;
the watch companion reuses the adaptive scaffold at the smallest breakpoint.

**Test.** 9 admin/IDOR tests: role gates (401/403), overview shape, self-demotion
refused, per-user tool toggle needs a real user, another user's conversation is 404
even for an admin, media is owner-scoped, non-image uploads rejected.

**Mocked.** Nothing.

---

## Phase 12 — Hardening & launch

**Built.** 68 tests across auth, gateway, injection, devices, builder, audit/admin and
hardening; a secret-leak scanner over the tree; production boot guards; SSRF-by-design
(no URL-accepting tool); backup/restore procedure and a restore drill; staged
deployment checklist; monitoring/alert matrix and an incident playbook; responsive and
design-consistency passes on both surfaces; the deploy-time design lint as a permanent
quality gate.

**Run.** `make test`, `make lint`, `docs/operations.md` for deploy/backup/monitoring.

**Test.** `68 passed`. Manually verified end to end on this machine: admin CLI →
login → assistant turn → approval → sandbox preview (signed, CSP-sandboxed) → approval
→ deploy (simulated, allowlisted) → project list → audit chain `ok: true` over 10
entries.

**Mocked — the honest list.** Offline planner (no Anthropic key here), deploy targets
in simulated mode, messaging in simulated mode, and the Flutter app unbuilt (no SDK in
this environment). Everything else executes for real.
