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
│  harness ──▶ llm adapter (claude | openai | offline planner)         │
│         └──▶ security gateway ──▶ tool registry ──▶ integrations      │
│                                    (21 plugins)      HA · IMAP ·      │
│  builder (sandbox, lint, preview) · audit (hash chain) · worker       │
│                                                      search · msg ·   │
│                                                      github/vercel    │
└──────────────────────────────────────────────────────────────────────┘
                               │
                    Postgres (or SQLite) + Redis
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

## Why an adapter

`LLMAdapter.complete(messages, tool_schemas) -> LLMResponse` is the only surface the
harness knows. `ClaudeAdapter` (Anthropic Messages API, tool use, pooled keys from
the same organisation), `OpenAIAdapter` and `MockAdapter` implement it. Swapping
providers is one config value; the gateway, tools, approvals and audit are untouched.

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
`integration_connections` (secret *references* only) · `generated_projects` ·
`messaging_profiles` · `automation_rules` · `conversations` · `messages` · `chat_runs` ·
`tickets` · `system_flags`.

## Scaling notes

* Postgres + Redis in production; Redis backs cross-worker rate limiting and the
  worker's scheduling.
* Stateless API processes: sessions live in the database, not memory.
* The harness is the only stateful loop and its state is persisted per run, so an
  approval survives a restart or a load-balancer hop.
* Deploy polling is bounded; a stuck Vercel deployment returns `TIMEOUT` instead of
  hanging a request.
