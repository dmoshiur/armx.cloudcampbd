"""Resend REST transactional email for authentication.

No SMTP is used. A 2xx response is recorded as ``accepted`` (request accepted),
never as ``delivered``: only a signed Resend/Svix webhook can advance the ledger
to sent/delivered/bounced/complained/failed. Raw recovery tokens and API keys are
never written to the database. In non-production without credentials, a local
outbox records the link with an explicit ``not_configured`` status so automated
tests can exercise the workflow without pretending an email was delivered.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.config import settings
from app.core.db import SessionLocal, as_utc, utcnow
from app.models import EmailDelivery, EmailDeliveryEvent

log = logging.getLogger(__name__)

STATUS_RANK = {
    "requested": 0,
    "not_configured": 0,
    "accepted": 1,
    "delayed": 2,
    "sent": 3,
    "delivered": 4,
    "complained": 5,
    "bounced": 5,
    "failed": 6,
}

EVENT_STATUS = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.suppressed": "bounced",
    "email.failed": "failed",
}


@dataclass(slots=True)
class DeliveryPlan:
    delivery_id: str
    idempotency_key: str
    status: str  # queued | cooldown | duplicate
    cooldown_seconds: int = 0


@dataclass(slots=True)
class ProviderResult:
    ok: bool
    provider_message_id: str = ""
    attempts: int = 0
    error: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Branded templates
# ---------------------------------------------------------------------------
def _shell(heading: str, intro: str, button_label: str, link: str, warning: str, expiry: str) -> str:
    safe_link = html.escape(link, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(heading)} — A.R.M.X AI</title>
</head>
<body style="margin:0;padding:0;background:#010503;color:#d7ffe1;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#010503;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;border:1px solid #174d24;border-radius:14px;background:#06120a;overflow:hidden;">
        <tr><td style="padding:28px 32px 18px;border-bottom:1px solid #174d24;">
          <div style="display:inline-block;width:38px;height:38px;line-height:38px;text-align:center;border:1px solid #00ff41;border-radius:9px;background:#00ff41;color:#010503;font-weight:800;font-size:18px;">A</div>
          <span style="margin-left:12px;color:#d7ffe1;font-size:18px;font-weight:700;letter-spacing:-0.02em;vertical-align:middle;">A.R.M.X AI</span>
          <div style="margin-top:6px;color:#75a881;font-size:10px;letter-spacing:0.22em;text-transform:uppercase;">Control Intelligence</div>
        </td></tr>
        <tr><td style="padding:32px;">
          <h1 style="margin:0 0 16px;color:#d7ffe1;font-size:24px;line-height:1.25;font-weight:700;">{html.escape(heading)}</h1>
          <p style="margin:0 0 24px;color:#a8d5b2;font-size:15px;line-height:1.65;">{html.escape(intro)}</p>
          <table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:8px;background:#00ff41;">
            <a href="{safe_link}" style="display:inline-block;padding:13px 24px;color:#010503;font-size:14px;font-weight:800;text-decoration:none;">{html.escape(button_label)}</a>
          </td></tr></table>
          <p style="margin:24px 0 0;color:#75a881;font-size:13px;line-height:1.6;">{html.escape(expiry)}</p>
          <div style="margin-top:24px;padding:14px 16px;border:1px solid #174d24;border-radius:8px;background:#020904;">
            <p style="margin:0;color:#ffd58a;font-size:12px;line-height:1.6;"><strong>Security notice:</strong> {html.escape(warning)}</p>
          </div>
          <p style="margin:24px 0 0;color:#75a881;font-size:12px;line-height:1.6;">If the button does not work, copy this absolute recovery URL into your browser:</p>
          <p style="margin:6px 0 0;word-break:break-all;color:#00ff41;font-size:11px;line-height:1.6;">{safe_link}</p>
        </td></tr>
        <tr><td style="padding:18px 32px;border-top:1px solid #174d24;color:#75a881;font-size:11px;line-height:1.6;">
          A.R.M.X AI · CONTROL INTELLIGENCE<br />This is a transactional security message. No password or API key is included.
        </td></tr>
      </table>
      <p style="margin:18px 0 0;color:#4b7054;font-size:11px;">© {utc_now().year} A.R.M.X AI. All rights reserved.</p>
    </td></tr>
  </table>
</body>
</html>"""


def password_reset_email(link: str, ttl_minutes: int) -> tuple[str, str, str]:
    subject = "Reset your A.R.M.X AI password"
    heading = "Reset Your Password"
    intro = "A password reset was requested for your A.R.M.X AI account. Use the secure single-use link below to choose a new password."
    expiry = f"This link expires in {ttl_minutes} minutes and can be used only once."
    warning = "If you did not request this, ignore the email — your password stays unchanged. A.R.M.X AI will never ask for your password or API keys by email."
    text = (
        "A.R.M.X AI — CONTROL INTELLIGENCE\n\n"
        f"{heading}\n\n{intro}\n\n"
        f"Reset password: {link}\n\n{expiry}\n\n"
        f"Security notice: {warning}\n\n"
        "If the button or link does not work, copy the absolute URL above into your browser.\n"
        "This message contains no password or API key.\n"
    )
    return subject, _shell(heading, intro, "Reset Password", link, warning, expiry), text


def verification_email(link: str, ttl_hours: int) -> tuple[str, str, str]:
    subject = "Confirm your A.R.M.X AI email"
    heading = "Verify Your Email"
    intro = "Welcome to A.R.M.X AI. Confirm this address to finish securing your account and enable verified access."
    expiry = f"This verification link expires in {ttl_hours} hours and can be used only once."
    warning = "If you did not create this account, ignore this email. Never share verification links, passwords or API keys with anyone."
    text = (
        "A.R.M.X AI — CONTROL INTELLIGENCE\n\n"
        f"{heading}\n\n{intro}\n\n"
        f"Verify email: {link}\n\n{expiry}\n\n"
        f"Security notice: {warning}\n\n"
        "Copy the absolute URL above into your browser if the button does not work.\n"
    )
    return subject, _shell(heading, intro, "Verify Email", link, warning, expiry), text


# ---------------------------------------------------------------------------
# Delivery queue
# ---------------------------------------------------------------------------
async def recent_delivery(
    db: AsyncSession, recipient: str, purpose: str, cooldown_seconds: int | None = None
) -> EmailDelivery | None:
    window = cooldown_seconds if cooldown_seconds is not None else settings.EMAIL_RESEND_COOLDOWN_SECONDS
    since = utcnow() - timedelta(seconds=window)
    row = (
        await db.execute(
            select(EmailDelivery)
            .where(
                EmailDelivery.recipient == recipient.lower(),
                EmailDelivery.purpose == purpose,
                EmailDelivery.created_at >= since,
            )
            .order_by(EmailDelivery.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def queue_email(
    db: AsyncSession,
    *,
    to: str,
    purpose: str,
    subject: str,
    html_body: str,
    text_body: str,
    user_id: str | None,
    token_id: str,
    request_id: str,
    link: str,
    background: BackgroundTasks | None = None,
) -> DeliveryPlan:
    """Create one durable delivery record, then send asynchronously.

    A 60-second cooldown and a stable idempotency key derived from the token id
    protect against duplicate requests and transient retries. The raw link is
    only held in memory for the background task, never persisted.
    """
    recipient = to.lower().strip()
    existing_recent = await recent_delivery(db, recipient, purpose)
    if existing_recent is not None:
        age = (utcnow() - as_utc(existing_recent.created_at)).total_seconds()
        remaining = max(1, int(settings.EMAIL_RESEND_COOLDOWN_SECONDS - age))
        return DeliveryPlan(existing_recent.id, existing_recent.idempotency_key, "cooldown", remaining)

    idempotency_key = hashlib.sha256(f"{purpose}:{token_id}:{recipient}".encode()).hexdigest()
    duplicate = (
        await db.execute(select(EmailDelivery).where(EmailDelivery.idempotency_key == idempotency_key))
    ).scalar_one_or_none()
    if duplicate is not None:
        return DeliveryPlan(duplicate.id, idempotency_key, "duplicate")

    delivery = EmailDelivery(
        user_id=user_id,
        recipient=recipient,
        purpose=purpose,
        subject=subject,
        provider="resend",
        status="requested",
        idempotency_key=idempotency_key,
        request_id=request_id[:64],
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)

    if background is not None:
        background.add_task(
            deliver_by_id,
            delivery.id,
            recipient,
            subject,
            html_body,
            text_body,
            link,
            request_id,
            idempotency_key,
        )
    else:
        await deliver_by_id(
            delivery.id,
            recipient,
            subject,
            html_body,
            text_body,
            link,
            request_id,
            idempotency_key,
        )
    return DeliveryPlan(delivery.id, idempotency_key, "queued")


async def _resend_send(
    *, to: str, subject: str, html_body: str, text_body: str, idempotency_key: str
) -> ProviderResult:
    """POST /emails with bounded, idempotent retries. 2xx means accepted."""
    if not settings.resend_configured:
        return ProviderResult(False, error="RESEND_API_KEY and RESEND_FROM_EMAIL are not configured")
    payload = {
        "from": settings.RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key[:256],
        "User-Agent": "armx-ai-auth/1.0",
    }
    last_error = ""
    attempts = 0
    async with httpx.AsyncClient(timeout=settings.RESEND_TIMEOUT_SECONDS) as client:
        for attempt in range(1, settings.RESEND_MAX_ATTEMPTS + 1):
            attempts = attempt
            try:
                response = await client.post(settings.RESEND_API_URL, json=payload, headers=headers)
            except httpx.RequestError as exc:
                last_error = f"network error: {type(exc).__name__}"
                if attempt < settings.RESEND_MAX_ATTEMPTS:
                    await asyncio.sleep(0.4 * (2 ** (attempt - 1)))
                    continue
                break
            if 200 <= response.status_code < 300:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                message_id = str(body.get("id") or "")
                if not message_id:
                    return ProviderResult(False, attempts=attempts, error="Resend accepted the request but returned no message id")
                return ProviderResult(True, provider_message_id=message_id, attempts=attempts)
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable:
                # 400/401/403/409/422 are configuration or payload errors; do not retry.
                break
            if attempt < settings.RESEND_MAX_ATTEMPTS:
                retry_after = response.headers.get("retry-after", "")
                delay = float(retry_after) if retry_after.isdigit() else 0.4 * (2 ** (attempt - 1))
                await asyncio.sleep(min(5.0, delay))
    return ProviderResult(False, attempts=attempts, error=last_error or "Resend request failed")


def _write_local_outbox(*, to: str, subject: str, link: str, reason: str) -> None:
    """Explicit non-production sink. Never claims a real email was delivered."""
    outbox = Path("var")
    outbox.mkdir(exist_ok=True)
    with (outbox / "outbox.log").open("a", encoding="utf-8") as fh:
        fh.write(
            f"\n--- to={to} subject={subject} status=not_configured reason={reason} ---\n"
            f"Recovery/verification link (no email was sent): {link}\n"
        )
    log.warning("Resend not configured; recorded an explicit not_configured outbox entry for %s", to)


async def deliver_by_id(
    delivery_id: str,
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    link: str,
    request_id: str,
    idempotency_key: str,
) -> None:
    async with SessionLocal() as db:
        delivery = await db.get(EmailDelivery, delivery_id)
        if delivery is None:
            log.error("Email delivery %s vanished before send", delivery_id)
            return
        if delivery.status in {"accepted", "sent", "delivered", "bounced", "complained", "failed"}:
            return
        if not settings.resend_configured:
            if settings.is_production:
                status = "failed"
                error = "Resend is not configured; no authentication email was sent."
                log.error("Auth email delivery %s failed: %s", delivery_id, error)
            else:
                status = "not_configured"
                error = "Resend is not configured in this environment; no real email was sent."
                _write_local_outbox(to=to, subject=subject, link=link, reason=error)
            delivery.status = status
            delivery.last_error = error
            delivery.failed_at = utcnow() if status == "failed" else None
            await audit(
                db,
                action=f"email.{status}",
                status="error" if status == "failed" else "denied",
                detail={"delivery_id": delivery_id, "request_id": request_id, "reason": error},
                _commit=False,
            )
            await db.commit()
            return

        result = await _resend_send(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            idempotency_key=idempotency_key,
        )
        delivery.attempts = result.attempts
        if result.ok:
            delivery.status = "accepted"  # request accepted, NOT delivered
            delivery.provider_message_id = result.provider_message_id
            delivery.accepted_at = utcnow()
            delivery.last_error = ""
            await audit(
                db,
                action="email.accepted",
                detail={
                    "delivery_id": delivery_id,
                    "request_id": request_id,
                    "provider_message_id": result.provider_message_id,
                    "note": "Resend accepted the API request; delivery is unconfirmed until a signed webhook.",
                },
                _commit=False,
            )
            log.info(
                "Resend accepted auth email %s provider_id=%s request_id=%s (delivery not yet confirmed)",
                delivery_id,
                result.provider_message_id,
                request_id,
            )
        else:
            delivery.status = "failed"
            delivery.last_error = result.error[:1000]
            delivery.failed_at = utcnow()
            await audit(
                db,
                action="email.failed",
                status="error",
                detail={"delivery_id": delivery_id, "request_id": request_id, "error": result.error[:500]},
                _commit=False,
            )
            log.error("Resend auth email %s failed after %s attempts: %s", delivery_id, result.attempts, result.error)
        await db.commit()


# ---------------------------------------------------------------------------
# Signed Resend / Svix webhook verification and status tracking
# ---------------------------------------------------------------------------
def verify_resend_signature(raw_body: bytes, headers: Any) -> bool:
    secret = settings.RESEND_WEBHOOK_SECRET
    if not secret:
        return False
    svix_id = str(headers.get("svix-id", ""))
    timestamp = str(headers.get("svix-timestamp", ""))
    signature_header = str(headers.get("svix-signature", ""))
    if not (svix_id and timestamp and signature_header):
        return False
    try:
        now = int(time.time())
        signed_at = int(timestamp)
        if abs(now - signed_at) > 300:
            return False
        encoded = secret.split("_", 1)[1] if secret.startswith(("whsec_", "whsecret_v1_")) else secret
        key = base64.b64decode(encoded, validate=True)
        signed = f"{svix_id}.{timestamp}.".encode() + raw_body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        return any(
            hmac.compare_digest(part[3:], expected)
            for part in signature_header.split()
            if part.startswith("v1,")
        )
    except (ValueError, IndexError, TypeError):
        return False


async def record_email_event(db: AsyncSession, payload: dict[str, Any], event_id: str) -> str:
    """Idempotently apply a signed provider event. Returns a short outcome."""
    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_id = str(data.get("email_id") or data.get("id") or "")
    status = EVENT_STATUS.get(event_type, "")
    duplicate = (
        await db.execute(select(EmailDeliveryEvent.id).where(EmailDeliveryEvent.event_id == event_id))
    ).scalar_one_or_none()
    if duplicate:
        return "duplicate"

    delivery: EmailDelivery | None = None
    if message_id:
        delivery = (
            await db.execute(
                select(EmailDelivery).where(EmailDelivery.provider_message_id == message_id).limit(1)
            )
        ).scalar_one_or_none()

    safe_detail = {
        "type": event_type,
        "email_id": message_id,
        "bounce_type": str(data.get("bounce", {}).get("type") or "") if isinstance(data.get("bounce"), dict) else "",
        "created_at": str(data.get("created_at") or "")[:64],
        "status": status or "ignored",
    }
    row = EmailDeliveryEvent(
        delivery_id=delivery.id if delivery else None,
        event_id=event_id[:160],
        event_type=event_type[:80],
        status=status or "ignored",
        provider_message_id=message_id[:160],
        detail=json.dumps(safe_detail, default=str)[:4000],
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return "duplicate"

    if delivery and status:
        current_rank = STATUS_RANK.get(delivery.status, 0)
        next_rank = STATUS_RANK.get(status, 0)
        # A bounce/complaint/failure is terminal even after a delivered event.
        if next_rank > current_rank or status in {"bounced", "complained", "failed"}:
            delivery.status = status
            now = utcnow()
            if status == "sent":
                delivery.sent_at = now
            elif status == "delivered":
                delivery.delivered_at = now
            elif status in {"bounced", "complained", "failed"}:
                delivery.failed_at = now
            delivery.last_error = "" if status in {"sent", "delivered", "delayed"} else f"Provider event: {event_type}"
        await audit(
            db,
            action=f"email.{status or 'event'}",
            status="error" if status in {"bounced", "complained", "failed"} else "ok",
            detail={"delivery_id": delivery.id, "event_id": event_id, "event_type": event_type},
            _commit=False,
        )
    else:
        await audit(
            db,
            action="email.unmatched_event",
            status="ignored",
            detail={"event_id": event_id, "event_type": event_type, "provider_message_id": message_id},
            _commit=False,
        )
    await db.commit()
    return "matched" if delivery and status else ("unmatched" if not delivery else "ignored")


async def email_health(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(EmailDelivery.status, func.count(EmailDelivery.id)).group_by(EmailDelivery.status)
        )
    ).all()
    return {
        "provider": "resend",
        "configured": settings.resend_configured,
        "webhook_configured": bool(settings.RESEND_WEBHOOK_SECRET),
        "from_configured": bool(settings.RESEND_FROM_EMAIL),
        "base_url": settings.auth_base_url,
        "status_counts": {str(status): int(count) for status, count in rows},
        "note": "accepted means the Resend API accepted the request; delivered requires a signed webhook event.",
    }
