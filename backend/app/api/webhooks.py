"""Authenticated inbound callbacks from third-party messaging providers.

Webhook endpoints cannot use a user JWT: Meta calls them directly. They instead
use a one-time verification challenge for subscription setup and an HMAC over
the exact POST body for every delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.mailer import record_email_event, verify_resend_signature
from app.core.security import rate_limiter
from app.core.deps import client_ip

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(settings.WHATSAPP_VERIFY_TOKEN and settings.WHATSAPP_APP_SECRET)


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify_whatsapp(
    mode: str = Query(default="", alias="hub.mode", max_length=32),
    verify_token: str = Query(default="", alias="hub.verify_token", max_length=512),
    challenge: str = Query(default="", alias="hub.challenge", max_length=512),
) -> PlainTextResponse:
    """Complete Meta's GET subscription challenge.

    ``WHATSAPP_TOKEN`` is never accepted here: it is a Graph API access token,
    not the independently generated webhook verification token.
    """
    if not _configured():
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured")
    if mode != "subscribe" or not challenge or not hmac.compare_digest(
        verify_token, settings.WHATSAPP_VERIFY_TOKEN
    ):
        raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")
    return PlainTextResponse(challenge, status_code=200)


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > settings.WHATSAPP_WEBHOOK_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.WHATSAPP_WEBHOOK_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
    return bytes(body)


def _message_count(payload: dict[str, Any]) -> int:
    """Count valid message envelopes without logging message text or senders."""
    count = 0
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            messages = value.get("messages") if isinstance(value, dict) else None
            if isinstance(messages, list):
                count += sum(isinstance(message, dict) and bool(message.get("id")) for message in messages)
    return count


@router.post("/whatsapp")
async def receive_whatsapp(request: Request) -> dict[str, Any]:
    """Authenticate and acknowledge a WhatsApp delivery.

    This endpoint intentionally does not auto-reply. Inbound content must first
    be mapped to an explicitly approved tenant/contact before it may enter the
    assistant harness; accepting a signed event is not consent to execute tools.
    """
    if not _configured():
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured")

    body = await _bounded_body(request)
    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=400, detail="Unsupported WhatsApp webhook payload")

    message_count = _message_count(payload)
    # Keep logs metadata-only: message text, phone numbers and profile names are
    # deliberately excluded.
    log.info("Accepted signed WhatsApp webhook with %s message envelope(s)", message_count)
    return {"status": "accepted", "messages": message_count}


# ---------------------------------------------------------------------------
# Resend / Svix delivery events (accepted -> sent/delivered/bounced/failed)
# ---------------------------------------------------------------------------
RESEND_WEBHOOK_MAX_BYTES = 64 * 1024


async def _bounded_resend_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > RESEND_WEBHOOK_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > RESEND_WEBHOOK_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
    return bytes(body)


@router.post("/resend")
async def receive_resend(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Verify the exact signed bytes, deduplicate on svix-id, then advance status.

    The endpoint is inert (503) until RESEND_WEBHOOK_SECRET is configured. A
    forged or replayed event cannot mark email as delivered.
    """
    if not settings.RESEND_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Resend webhook is not configured")
    ok, _ = rate_limiter.hit(f"webhook:resend:{client_ip(request)}", 120)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many webhook attempts")
    raw = await _bounded_resend_body(request)
    if not verify_resend_signature(raw, request.headers):
        raise HTTPException(status_code=401, detail="Invalid Resend webhook signature")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")
    event_id = str(request.headers.get("svix-id", ""))[:160]
    outcome = await record_email_event(db, payload, event_id)
    return {"status": "accepted", "outcome": outcome, "event_id": event_id}
