# A.R.M.X AI engineering checklist

Last updated: 2026-11-04 (Asia/Dhaka)  
Branch: `arena/cd1dac40-armx-cloudcampbd`  
Baseline: `84368ff1c9ab2db0b0d789c80c5380909d3a7a85`

Status legend:

- **PASS** — exercised by an automated test, build, migration or live HTTP check in this workspace.
- **CONFIG** — implemented and unit/integration tested where possible, but a real provider credential/domain/deployment is still required.
- **UNVERIFIED** — cannot be honestly claimed here because the tool, credential, browser or reference asset is unavailable.

Nothing in this checklist treats API acceptance as email delivery, a simulated deploy as a live URL, or an implemented control as a completed visual/browser test.

## 1. Verification actually run

| Check | Command / probe | Result |
|---|---|---|
| Backend import / route registration | `ENV=test .venv/bin/python -c "from app.main import create_app; ..."` | **PASS** — `routes 138` |
| Complete backend suite | `cd backend && ENV=test .venv/bin/python -m pytest -q` | **PASS** — `100 passed in 33.31s` |
| Frontend type-check | `cd web && ./node_modules/.bin/tsc --noEmit` | **PASS** — `TSC_OK` |
| Production web build | `cd web && npm run build` | **PASS** — Next 15.5.28, `23/23` static pages |
| Fresh Alembic chain | `alembic upgrade head`, `downgrade b7e41c9d2a10`, `upgrade head` on isolated SQLite | **PASS** — `401b12a50450 → 6a2f7c4d91b8 → 9b31d0f2a6e7 → b7e41c9d2a10 → c9f2a1d34e77`; downgrade/upgrade of the new migration succeeded |
| Live HTTP through the Next `/api` proxy | backend on `0.0.0.0:8000`, Next on `0.0.0.0:3000` | **PASS** — `/api/health`, `/api/config`, `/api/matrix/status`, `/api/auth/csrf`, `/api/webhooks/resend` and all 16 user-facing routes returned expected statuses |
| Cookie + CSRF flow | signup → `/api/auth/csrf` → `PATCH /api/preferences` | **PASS** — `201`, `200`, missing CSRF `403`, matching CSRF `200`; DB-backed preferences persisted |
| Matrix transport honesty | `/api/matrix/status`, ticket, SSE and WebSocket | **PASS** — capability status honestly `available:false`; SSE returned an `error` event; WS sent the same honest error then closed `4404`. No claim that the original binary ran |
| Admin authorization | `GET /api/admin/email-deliveries` with no bearer, user bearer and admin bearer | **PASS** — `401`, `403`, `200` in tests; live no-auth probe returned `401` |
| Frontend secret bundle scan | precise regex over `web/.next/static` and `web/.next/server` | **PASS** — `NO_FRONTEND_SECRET_VALUES`; variable names in UI copy are not secret values |
| Tracked-source credential scan | `git grep` for provider key patterns and non-empty secret assignments | **PASS** — only `GROQ_API_KEY="YOUR_GROQ_KEY"` placeholder in README |
| GitHub Actions PR #5 | `Validate containers`: `tests` + `root-image` | **PASS** — `tests` passed in `6m6s`; `root-image` passed in `1m0s`. Backend tests, container entrypoint tests, frontend dependency/type check, Flutter Android analyze/compile, Dockerfile build, migrations/web/API/signup through the public nginx port all passed |
| nginx config / public-port proxy | static brace/directive/WS checks plus full-stack smoke test | **PASS** — both configs are statically valid; the CI `root-image` job started the full stack on a non-default runtime port and verified migrations, web, API and signup through nginx. `nginx -t` itself was not run locally because the binary is absent |
| Dockerfile / real CMatrix package installation | `cmatrix`, `ncurses-term` and GPL notice copy present; CI image build | **PASS** — GitHub Actions built the repository-root Dockerfile and smoke-tested the full stack. Local `docker` binary is unavailable, but the image build is no longer unverified |
| Reference image | `https://i.postimg.cc/Kk4TjwHS/image.png` | **UNVERIFIED** — Postimages HTML was reachable but the displayed/download image endpoints failed (`OpenSSL SSL_connect` / HTTP 500); design was recreated from the written direction only |
| Browser console, network trace, pixel overflow | browser automation | **UNVERIFIED** — no browser tool, viewport screenshot or console trace is available in this workspace |

## 2. Original overhaul

| Item | Status | Evidence / note |
|---|---|---|
| Structured errors, request IDs, actionable status and retry hints | **PASS** | Rewritten `web/lib/api/client.ts`; assistant UI and tests/build exercise typed errors; live `/api/config` and proxy responses are JSON |
| Durable streaming assistant with SSE, stop, retry and run expiry | **PASS** | `backend/app/api/assistant.py`, `app/harness.py`, `web/app/(app)/page.tsx`; Next build and full pytest pass |
| Persistent conversations, messages, feedback, edit/regenerate/export | **PASS** | `Conversation` API and `/conversations` page; build and tests pass |
| Approval countdown, exact args/hash, high-risk confirmation, retry | **PASS** | `ApprovalCard` and backend retry endpoint; build/type-check pass |
| Exact provider/model reporting; no silent model switch | **PASS** | `/models`, DB routing and stream events; capabilities page reports DB status |
| 21 typed tools with schemas, permissions, timeout and output contract | **PASS** | `/tools/registry` page and `Tool Registry`; backend suite loads 21 tools |
| Honest deployment: no fabricated `READY` URL or persisted success | **PASS** | Builder tests updated; `/projects` and `/builder` show provider-confirmed URLs only; `render.yaml` now uses `PIPELINE_MODE=live` and unconfigured providers report `not_configured` |
| Site Builder generate/edit/regenerate/version/restore/download/preview | **PASS** | New `POST /projects/generate` and `POST /projects/{id}/regenerate-component`; full builder page with iframe sandbox, three viewport widths, file editor, snapshots and ZIP download; build passes |
| DB-backed preferences and memory; explicit capture only | **PASS** | `/preferences`, `/memory`, `/memory/search`, `/memory/capture/{message_id}`; Settings and Memory pages; live `PATCH /preferences` returned `200` |
| Automations, activity, usage analytics, provider health | **PASS** | `/automations`, `/activity`, `/analytics/usage`, `/health/providers` pages/endpoints; build passes |
| Original CMatrix PTY, WS→SSE, one-use tickets, honest MIT fallback | **PASS (transport)** / **CONFIG (binary)** | Dockerfile installs `cmatrix`; local sandbox has no binary, so status/SSE/WS correctly reported unavailable. Docker build is still required to verify the real PTY in production |
| GPL-3.0 notice and vendored MIT fallback licence | **PASS** | `third_party/cmatrix/NOTICE.md`, `web/lib/vendor/{LICENSE,cmatrix.mjs,cmatrix.d.mts}`; npm `cmatrix` dependency removed and lockfile regenerated |
| nginx WebSocket upgrade forwarding | **PASS (static + CI proxy)** | both nginx configs contain `/api/matrix/ws` upgrade headers; CI full-stack public-port smoke test passed. `nginx -t` was not run locally |
| 12 navigation destinations and keyboard-aware shell | **PASS** | all 16 listed app/auth routes returned `200` live; `/conversations`, `/projects`, `/capabilities`, `/tools`, `/automations`, `/memory`, `/activity` are now real pages |
| Compact/fixed composer, safe Markdown, attachments, read-aloud, search | **PASS** | assistant page and components; production build passes |
| Reduced motion, hidden-tab pausing and bounded Matrix renderer | **PASS (implementation)** / **UNVERIFIED (visual)** | controls/status exist; no browser viewport/console trace here |
| Flutter Android client | **PASS (CI compile)** | GitHub Actions `Analyze and compile Flutter Android client` passed; no physical-device runtime test was performed |
| Full `docs/AUDIT.md` review update | **PASS** | baseline audit retained; post-implementation section added |
| `docs/ENGINEERING_CHECKLIST.md` | **PASS** | this file |

## 3. Secure authentication acceptance

| Requirement | Status | Evidence / note |
|---|---|---|
| Visual direction from Postimages reference | **UNVERIFIED** | image fetch failed; compact near-black card, `A.R.M.X AI` / `CONTROL INTELLIGENCE`, emerald action, subtle borders and responsive CSS were implemented from the written description |
| Existing accounts / DB / session architecture / RBAC preserved | **PASS** | additive migration only; legacy bearer tokens still work; 90 pre-existing tests plus admin/user authorization tests pass |
| Invalid credentials and generic login errors | **PASS** | `test_auth.py` and reset-flow tests assert identical `Invalid email or password` |
| Email, password, show/hide, remember, forgot, loading, inline errors, keyboard labels | **PASS (implementation/build)** / **UNVERIFIED (visual)** | compact auth UI, accessible labels and inline errors; production build passes; no browser pixel/keyboard trace |
| Intended-destination redirect; Assistant default | **PASS (implementation)** | `useAuth` reads a validated relative `next`; login/callback route to `/` |
| Remember-me session TTL | **PASS** | test asserts short ~12h session when off and >24h session when on |
| Forgot-password generic message exactly as specified | **PASS** | test asserts `If an account exists for this email, you will receive password recovery instructions shortly.` for known, unknown and duplicate requests |
| Real Resend email | **CONFIG** | official REST call, templates, idempotency, retries and webhook are mocked-tested; no real `RESEND_API_KEY` or live mailbox available here |
| Absolute HTTPS recovery/verification links based on `APP_BASE_URL` | **PASS** | tests parse `https://armx.example/...` links from both HTML and plain-text parts |
| 15-minute reset expiry / 24-hour verification expiry | **PASS** | config defaults and expired-token test return `400`; email copy states expiry |
| Single-use hashed tokens, no raw token at rest | **PASS** | tests inspect `PasswordResetToken` / `EmailVerificationToken` hashes and assert no `pr_`/`ev_` raw token |
| Password persists, old password fails | **PASS** | reset test verifies Argon2 hash with new password and rejects old password |
| Old sessions revoked; no auto-login from reset | **PASS** | all sessions marked revoked; `/api/auth/me` returns `401` immediately after reset |
| Registration full name/email/password/confirm/terms/strength/duplicate handling | **PASS** | `/register` test, duplicate `409` generic conflict test; public role is always `user` |
| Verification email/link, single-use, status and policy gate | **PASS** | verification test covers POST verify, GET compatibility, reuse failure, `is_verified`, and `REQUIRE_EMAIL_VERIFICATION=true` blocking protected `/me` |
| 60-second resend cooldown | **PASS** | verification and reset cooldown tests assert one token and one delivery; UI shows countdown |
| Email failure logging and no indefinite invalid retries | **PASS** | 422 provider response produces `status=failed`, `attempts=1`, `last_error`, audit `email.failed`; direct test asserts no retry |
| Accept/sent/delivered/bounced/failed distinction | **PASS** | mocked `accepted` ledger; signed webhook events advance to `delivered` then terminal `bounced`; duplicate event dedupe tested |
| Signed Resend/Svix webhook, replay window, admin ledger | **PASS** | forged/old/unconfigured events rejected; valid events matched; admin/user/no-auth ledger access tested |
| No SMTP required; no API key in frontend or source | **PASS** | `smtplib` absent from mailer; backend `.env.example` SMTP entries removed; production bundle scan found no secret values; `/api/config` returns flags only |
| Admin roles/permissions intact | **PASS** | admin ledger test and existing admin suite pass; public registration never grants admin |
| Responsive desktop/tablet/phone | **PASS (build/CSS)** / **UNVERIFIED (visual)** | responsive classes and auth CSS build; no browser screenshot or overflow trace |
| Login visual match, browser console/network, real mobile gestures | **UNVERIFIED** | explicitly not claimed complete |

## 4. What remains before a real deployment is fully live

1. **Resend**: create an account/key, verify a custom domain with DKIM/SPF/DMARC records, set a branded sender, copy the webhook signing secret and register `https://<host>/api/webhooks/resend`. Follow `docs/RESEND_SETUP.md`. For initial testing, `onboarding@resend.dev` works only for the account owner's address.
2. **Render/environment**: fill every `sync: false` value in `render.yaml`: `APP_BASE_URL`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_WEBHOOK_SECRET`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `LLM_SECRETS_KEY`, `GROQ_API_KEY`, and one first-admin bootstrap. Keep all secrets server-side; production startup refuses missing/placeholder Resend values, non-HTTPS origins and insecure DB settings.
3. **Email policy**: `REQUIRE_EMAIL_VERIFICATION=false` preserves the existing permissive policy. Set it to `true` only after confirming the verified domain/webhook and that all existing users have verified addresses.
4. **Deployment integrations**: `PIPELINE_MODE=live` is set for production; add `GITHUB_TOKEN`, `VERCEL_TOKEN` and `GITHUB_ALLOWED_TARGETS` (or default org) only when real deployment is intended. Without them, the UI honestly reports `not_configured`.
5. **CMatrix**: the CI image build and full-stack smoke test passed, but no real PTY frame stream was exercised because the local sandbox has no `cmatrix` binary. Run the built image with the executable installed to verify authentic frames; the honest unavailable path and MIT fallback are already tested.
6. **Still unverified**: the `nginx -t` command itself (the full nginx public-port smoke test passed in CI), browser console/network/visual overflow, live Resend email/webhook, real CMatrix frame output and a real provider-confirmed deployment. These are **not** marked complete.
7. **Reference login art**: the Postimages image could not be downloaded; compare the compact auth pages against the original design in a browser and adjust spacing/type if a pixel-level match is required.

## 5. Commands used for final verification

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd backend && ENV=test .venv/bin/python -m pytest -q                 # 100 passed
cd web && npm ci --no-audit --no-fund
cd web && ./node_modules/.bin/tsc --noEmit                           # clean
cd web && npm run build                                              # 23/23 static pages
cd backend && ENV=test DATABASE_URL=sqlite+aiosqlite:////tmp/armx-mig-auth.db \
  AUTO_CREATE_TABLES=false JWT_SECRET=... LLM_SECRETS_KEY=... \
  .venv/bin/alembic upgrade head && ... downgrade b7e41c9d2a10 && ... upgrade head
```

Live local preview checks used `uvicorn app.main:app --host 0.0.0.0 --port 8000` and
`next start -H 0.0.0.0 -p 3000`; browser-facing `/api` requests went through the
Next rewrite, not `localhost` from client code.

GitHub Actions PR #5 additionally ran `Validate containers`: the `tests` job
passed backend tests, container entrypoint tests, frontend dependency/type
checks and Flutter Android analyze/compile; the `root-image` job built the root
Dockerfile, started the full stack through a non-default runtime port and
verified migrations, web, API and signup through nginx. The only annotations
were non-fatal Node.js 20 deprecation and Ubuntu image-migration notices.
