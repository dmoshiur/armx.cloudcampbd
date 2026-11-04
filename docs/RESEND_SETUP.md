# A.R.M.X AI — Resend configuration guide

Authentication email uses the **official Resend REST API** (`POST https://api.resend.com/emails`). No SMTP server, SMTP credentials or SMTP library is needed. All secrets stay server-side; the frontend receives only non-secret capability flags.

## Required environment variables

```dotenv
RESEND_API_KEY=
RESEND_FROM_EMAIL=
APP_BASE_URL=
```

Recommended for delivery-status tracking:

```dotenv
RESEND_WEBHOOK_SECRET=
```

Optional provider-compatible test override:

```dotenv
RESEND_API_URL=https://api.resend.com/emails
RESEND_MAX_ATTEMPTS=3
RESEND_TIMEOUT_SECONDS=10
```

`APP_BASE_URL` must be an absolute `https://` URL in production, e.g. `https://thamjj13.top`. If it is blank the existing `WEB_ORIGIN` is used. Recovery links are built as `${APP_BASE_URL}/reset-password?token=…`; verification links as `${APP_BASE_URL}/verify-email?token=…`.

## 1. Create a Resend account

1. Sign up at <https://resend.com>.
2. Complete the account email verification.
3. Open the **API Keys** page.

## 2. Create an API key

1. Click **Create API Key**.
2. Name it `armx-production` (or `armx-test`).
3. Grant **Sending access**; full access is not required for `/emails`.
4. Copy the `re_…` key once. Put it in `RESEND_API_KEY` on the server only.
5. Never commit it, never place it in `web/`, and never return it from `/api/config`.

## 3. Add a sending domain

1. Open **Domains → Add Domain**.
2. Enter your custom domain, e.g. `thamjj13.top` or a subdomain such as `mail.thamjj13.top`.
3. Choose the region closest to your users.

## 4. Configure DNS authentication records

Resend displays DNS records for the domain. Add them at your DNS provider:

- **DKIM** `TXT`/`CNAME` records for cryptographic signing.
- **SPF** `TXT` record (or merge the include into an existing SPF record).
- **DMARC** `TXT` record if you manage the domain policy.
- Optional **Return-Path / MX / tracking CNAME** records shown by Resend.

Do not delete unrelated existing mail records. DNS propagation can take minutes to hours.

## 5. Verify the domain

1. Return to **Domains** and click **Verify**.
2. Wait until DKIM, SPF and Return-Path (if shown) are all **Verified**.
3. If verification stays pending, re-check exact host/value strings and TTLs.

## 6. Configure the sender address

Production:

```dotenv
RESEND_FROM_EMAIL=A.R.M.X AI <no-reply@thamjj13.top>
```

The domain must match the verified sending domain. The display name is free text.

Initial testing without a verified domain (Resend onboarding restriction):

```dotenv
RESEND_FROM_EMAIL=A.R.M.X AI <onboarding@resend.dev>
```

`onboarding@resend.dev` can send **only to the email address associated with the Resend account**. Do not use it for real users. The recipient restriction is enforced by Resend; the application reports that failure honestly in the delivery ledger.

## 7. Add environment variables in Render

In the Render service → **Environment**:

| Key | Value |
|---|---|
| `RESEND_API_KEY` | `re_…` (mark secret / `sync: false`) |
| `RESEND_FROM_EMAIL` | verified branded sender |
| `APP_BASE_URL` | `https://<public-hostname>` |
| `RESEND_WEBHOOK_SECRET` | `whsec_…` (mark secret) |
| `REQUIRE_EMAIL_VERIFICATION` | `false` by default; set `true` to enforce verification |
| `WEB_ORIGIN` | public HTTPS origin if `APP_BASE_URL` is blank |
| `CORS_ORIGINS` | same public HTTPS origin |

`render.yaml` declares the Resend variables with `sync: false`; fill their values in the Render dashboard. No SMTP variables are required. Existing unused `SMTP_*` environment entries may remain but are ignored.

Production startup refuses to boot when `RESEND_API_KEY`, `RESEND_FROM_EMAIL` or an HTTPS `APP_BASE_URL`/`WEB_ORIGIN` is missing. This prevents silently dropping recovery email.

### Delivery webhook (recommended)

1. Resend → **Webhooks → Add Endpoint**.
2. Endpoint URL: `https://<public-hostname>/api/webhooks/resend`.
3. Subscribe to: `email.sent`, `email.delivered`, `email.delivery_delayed`, `email.bounced`, `email.complained`, `email.failed`, `email.suppressed`.
4. Copy the endpoint signing secret (`whsec_…`) into `RESEND_WEBHOOK_SECRET`.
5. The backend verifies the exact raw bytes with the Svix HMAC scheme, rejects timestamps outside ±5 minutes and deduplicates on `svix-id`.

Without the webhook secret, the endpoint returns `503` and no delivery status can be forged.

## 8. Test password recovery

1. Deploy with the variables above and run `alembic upgrade head` (the Docker entrypoint does this).
2. Open `/forgot-password` and submit the registered email.
3. Expect the generic response: `If an account exists for this email, you will receive password recovery instructions shortly.`
4. Check the Resend dashboard → **Emails** for a `Reset Your Password` message.
5. Open the absolute HTTPS link within **15 minutes**.
6. Enter and confirm a new password (10+ chars, uppercase, symbol).
7. Submit. All existing sessions are revoked; the page links back to `/login` rather than auto-signing in.
8. Reusing the same link returns `This reset link is invalid or already used`.
9. A second request within 60 seconds is rate-limited/cooldowned and does not mint a second usable token.
10. Sign in with the new password. Old password must fail.

### Registration / email verification

1. Open `/register`, submit a full name, email, strong password, confirmation and terms acceptance.
2. New accounts are always `user`; admin is never granted by public registration.
3. The verification email contains a single-use absolute HTTPS link valid for 24 hours.
4. `/verify-email` posts the token, marks the user verified and links to `/login`. Reuse fails.
5. Resend verification uses the same 60-second cooldown and a generic response that never reveals account existence.
6. With `REQUIRE_EMAIL_VERIFICATION=true`, unverified users cannot use protected functionality; with the existing default `false`, verification is optional but still recorded.

For local development without Resend credentials, no real email is claimed: the backend writes an explicit `not_configured` entry containing the local link to `backend/var/outbox.log`, and the delivery ledger records `not_configured`.

## 9. Check email delivery logs

- **Resend dashboard → Emails**: accepted/queued, sent, delivered, bounced, complained, failed with timestamps and raw event payloads.
- **Resend dashboard → Webhooks → Endpoint logs**: signature verification and retry attempts.
- **A.R.M.X AI Settings → System → Delivery ledger** (admins only) or `GET /api/admin/email-deliveries`: server-authorised ledger with request correlation IDs and status counts.
- **`/api/health/providers`** → `email`: configured capabilities and status counts.
- **Audit log**: `email.accepted`, `email.failed`, `email.delivered`, `email.bounced`, `email.complained`, `email.unmatched_event`.

### Status vocabulary

| Status | Meaning |
|---|---|
| `requested` | Durable delivery row created; provider call not yet completed |
| `accepted` | Resend API returned 2xx with a message id. **Not delivered.** |
| `sent` | Signed provider `email.sent` event |
| `delivered` | Signed provider `email.delivered` event |
| `delayed` | Signed `email.delivery_delayed` event |
| `bounced` / `complained` | Signed negative event; terminal |
| `failed` | Provider rejected, retries exhausted, or signed `email.failed` |
| `not_configured` | Local development sink only; no real email was sent |

The application never upgrades `accepted` to `delivered` without a signed webhook event. It never logs passwords, raw recovery tokens, or `RESEND_API_KEY`.
