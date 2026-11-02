# Architecture

## Layers

```
┌──────────────────────────────┐   ┌───────────────────────────────┐
│ web (Next.js + Tailwind)     │   │ app (Flutter: Android/desktop) │
│ dashboard · chat · builder   │   │ chat · voice · overlay bubble  │
│ devices · admin · settings   │   │ devices · alarms · watch       │
└──────────────┬───────────────┘   └───────────────┬───────────────┘
               │  HTTPS, one typed contract        │
               └───────────────┬───────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ nginx (TLS, limits)  │
                    └──────────┬───────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ FastAPI core                                                         │
│                                                                      │
│  api/auth      argon2 · JWT · rotating refresh · reset · Google OIDC │
│  api/assistant harness loop · approvals · conversations              │
│  api/devices   pairing · owner-password unlink · command queue       │
│  api/admin     users · tool toggles · audit · kill-switch            │
│                                                                      │
│  harness ──▶ weighted model router (Groq/compatible/Anthropic/offline)│
│         └──▶ security gateway ──▶ tool registry ──▶ integrations      │
│                                    (21 plugins)      HA · IMAP ·      │
│  builder (sandbox, lint, preview) · audit · in-process housekeeping  │
│                                                      search · msg ·   │
│                                                      github/vercel    │
└──────────────────────────────────────────────────────────────────────┘
                               │
             Turso primary ⇄ local embedded replica
```

## Request lifecycle: one assistant turn

1. `POST /api/assistant/chat {message, conversation_id}`.
2. The harness persists the user turn, seeds a durable `ChatRun` and calls the
   adapter with the tool schemas.
3. The adapter returns text and/or tool *requests*. Nothing is executed by the model.
4. For each request the gateway runs `preflight`:
   kill-switch → global toggle → per-user toggle → scope/role → rate limit → schema.
5. **LOW** risk → execute, append the result as untrusted data, continue the loop.
   **MEDIUM/HIGH** → create a single-use `Approval` bound to
   `sha256(tool ⧺ args ⧺ actor ⧺ session ⧺ expiry)`, persist the paused run, return
   `awaiting_approval` with the exact action for the confirm dialog.
6. `POST /api/assistant/runs/{id}/approve` burns the approval (no replay, no
   argument swapping), executes once, and resumes the same run.
7. The loop is bounded by `HARNESS_MAX_STEPS` (default 8) and every step is audited.

## Why adapters plus a router

`LLMAdapter.complete(messages, tool_schemas) -> LLMResponse` is the only surface the
harness knows. `RoutingAdapter` loads encrypted provider/model records, orders each
priority tier by configured weight, skips open circuits and fails over on errors.
`OpenAIAdapter` covers Groq and other compatible APIs; `ClaudeAdapter` covers the
Anthropic Messages protocol; `MockAdapter` is the labelled offline last resort.
The gateway, tools, approvals and audit remain provider-independent.

## Build & deploy pipeline

```
prompt ─▶ generator ─▶ {files} ─▶ design lint ─▶ preview (signed capability URL)
                                        │
                                        └─ fails → repair round (planner) or block
                                                    │
                                        human approval (repo + Vercel project shown)
                                                    ▼
                         GitHub (user's account if connected, else platform account)
                                                    ▼
                                    Vercel production deployment (polled)
                                                    ▼
                            optional project-scoped Turso database
```

Guardrails: file paths are canonicalised inside the workspace, sizes capped, the
destination repo/project is derived server-side and allowlisted, and the lint gate
blocks a deploy with error-level design violations.

## Data model (selected)

`users` · `sessions` · `password_reset_tokens` · `email_verification_tokens` ·
`linked_devices` · `device_unlink_events` · `device_commands` · `screen_share_sessions` ·
`tool_definitions` · `tool_user_overrides` · `approvals` · `audit_events` ·
`integration_connections` (secret *references* only) · `llm_providers` (Fernet ciphertext) ·
`llm_models` (weight, priority, circuit health) · `generated_projects` · `messaging_profiles` ·
`automation_rules` · `conversations` · `messages` · `chat_runs` · `tickets` · `system_flags`.

## Scaling notes

* Render production runs one API process owning one embedded Turso replica; Redis
  is not required. Pending local writes are retried before periodic pulls.
* Sessions and harness state live in Turso, so approvals survive process restarts.
* Horizontal scaling requires a separate replica path per instance plus a shared
  rate limiter and explicit migration leadership; it is intentionally not enabled
  by the single-instance Render template.
* Deploy polling is bounded; a stuck Vercel deployment returns `TIMEOUT` instead of
  hanging a request.
