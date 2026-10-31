# Build phases and status

Every phase below was implemented in this repository. "Live-gated" means the code
path is complete and tested, but the third-party side needs credentials you must
supply (they are never committed).

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Repo skeleton, architecture doc, threat model, risk matrix, shared design tokens | **done** | `docs/`, `design/tokens.json` |
| 1 | Docker Compose (nginx, api, worker, postgres, redis), typed settings with startup validation, models + Alembic, `/api/health` | **done** | `deploy/`, `backend/alembic/`, `core/config.py` |
| 2 | Auth: signup/login/JWT/refresh rotation, SMTP reset, Google OIDC, admin CLI, tool registry skeleton, audit writer, kill-switch | **done** (mail needs SMTP; Google needs OAuth client) | `api/auth.py`, `scripts/create_admin.py`, `audit/` |
| 3 | Security Gateway: tiers, hash-bound single-use approvals, rate limits; Claude adapter + bounded harness end to end | **done** (Claude needs a key; offline planner otherwise) | `security/`, `harness.py`, `llm/` |
| 4 | Web app shell: theme + components, auth screens, chat calling the real harness | **done** | `web/` |
| 5 | Flutter shell: theme/breakpoints/router/widgets, auth + chat, wake-word pipeline, overlay bubble | **source complete**, compiled only where a Flutter SDK exists | `app/` |
| 6 | Smart home: Home Assistant integration, entity allowlist, `set_light`/`get_state`, ESP32 demo | **done** (live-gated on HA) | `integrations/home_assistant.py`, `examples/` |
| 7 | Auto-build: sandbox generator, design lint, GitHub + Vercel + Turso, `web_generate`/`web_preview`/`web_deploy` | **done**, simulated mode by default | `builder/`, `integrations/github_vercel.py` |
| 8 | Call control, app launch, search | **done** (calls/app launch execute on the paired device; search live-gated) | `tools/call_control.py`, `open_app.py`, `web_search.py` |
| 9 | Linked devices: consent pairing, owner-password unlink, persistent notification, audit, read-only admin view | **done** | `api/devices.py`, `tools/link_device.py`, `unlink_device.py` |
| 10 | Messaging: WhatsApp/Messenger, personality profiles, auto-send vs draft-only with dynamic risk | **done**, simulated by default | `integrations/messaging.py`, `tools/messaging_reply.py` |
| 11 | Admin dashboard (users, audit viewer, tool toggles, kill-switch), watch companion wiring | **done** | `web/app/(app)/admin`, `app/lib/features/admin` |
| 12 | Hardening: security test suite, backup/restore drill, staged deploy, monitoring, responsive + design QA | **done** (drill documented and scripted; run it on your infra) | `backend/tests/`, `docs/operations.md` |

## Deliberate non-goals

* Rotating across personal Anthropic accounts to dodge plan limits — policy
  violation, not implemented; key pooling is limited to one organisation's keys.
* Silent interception of calls/SMS, hidden screen capture, or any device control the
  device cannot see and stop.
* A "just do it" mode that skips approvals for medium/high actions.
