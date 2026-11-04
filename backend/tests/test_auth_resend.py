"""Cookie auth, Resend REST, delivery events and production-guard tests.

These tests never contact Resend. The official REST call shape is exercised with
httpx.MockTransport, while acceptance/delivery/bounce states remain distinct.
No SMTP, real API key or real email is used.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core import mailer
from app.core.config import Settings, settings
from app.core.db import SessionLocal, as_utc
from app.core.security import hash_token, new_opaque_token, verify_password
from app.models import (
    AuditEvent,
    EmailDelivery,
    EmailDeliveryEvent,
    EmailVerificationToken,
    PasswordResetToken,
    Session,
    User,
)

GENERIC_RESET = "If an account exists for this email, you will receive password recovery instructions shortly."
GENERIC_VERIFICATION = "If an account exists and needs verification, you will receive instructions shortly."
STRONG_PASSWORD = "Sup3rSecret!"
NEW_PASSWORD = "BrandNew1!x"
_REAL_SLEEP = asyncio.sleep
_ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient
_SECRET_KEY = b"armx-webhook-secret-for-tests"
_SECRET_B64 = base64.b64encode(_SECRET_KEY).decode()
_WEBHOOK_SECRET = f"whsec_{_SECRET_B64}"


async def _signup(client: httpx.AsyncClient, email: str, password: str = STRONG_PASSWORD) -> dict[str, Any]:
    response = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "display_name": "Tester"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _one(stmt):
    async with SessionLocal() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def _all(stmt):
    async with SessionLocal() as session:
        return (await session.execute(stmt)).scalars().all()


async def _scalar(stmt):
    async with SessionLocal() as session:
        return (await session.execute(stmt)).scalar_one()


async def _wait_for_delivery(purpose: str, status: str | None = None, timeout: float = 2.0) -> EmailDelivery:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        row = await _one(
            select(EmailDelivery)
            .where(EmailDelivery.purpose == purpose)
            .order_by(EmailDelivery.created_at.desc())
            .limit(1)
        )
        if row is not None and row.status != "requested" and (status is None or row.status == status):
            return row
        await _REAL_SLEEP(0.01)
    raise AssertionError(f"Timed out waiting for {purpose} delivery status {status or 'non-requested'}")


async def _wait_for_captures(captured: list[dict[str, Any]], count: int, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while len(captured) < count and loop.time() < deadline:
        await _REAL_SLEEP(0.01)
    assert len(captured) >= count, f"Expected {count} Resend REST calls, got {len(captured)}"


def _install_resend_mock(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[tuple[int, dict[str, Any]]] | None = None,
    *,
    webhook_secret: str = "",
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    queue = list(responses or [])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append({"url": str(request.url), "headers": dict(request.headers), "json": body})
        if queue:
            status_code, payload = queue.pop(0)
        else:
            status_code, payload = 200, {"id": f"msg_auto_{len(calls)}"}
        return httpx.Response(status_code, json=payload)

    transport = httpx.MockTransport(handler)

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.inner = _ORIGINAL_ASYNC_CLIENT(transport=transport, base_url="https://mock.local")

        async def __aenter__(self):
            return self.inner

        async def __aexit__(self, *exc_info):
            await self.inner.aclose()

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key_1234567890")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "A.R.M.X AI <no-reply@armx.example>")
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setattr(settings, "RESEND_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://armx.example")
    monkeypatch.setattr(mailer.httpx, "AsyncClient", MockAsyncClient)
    monkeypatch.setattr(mailer.asyncio, "sleep", no_sleep)
    return calls


def _link(calls: list[dict[str, Any]], index: int, path: str) -> tuple[str, str]:
    html_body = calls[index]["json"]["html"]
    match = re.search(rf"https://armx\.example/{re.escape(path)}\?token=([A-Za-z0-9_\-]+)", html_body)
    assert match, f"No absolute HTTPS {path} link found in email HTML"
    return match.group(0), match.group(1)


def _signed_headers(raw: bytes, event_id: str, timestamp: int | None = None, *, valid: bool = True) -> dict[str, str]:
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{event_id}.{ts}.".encode() + raw
    signature = base64.b64encode(hmac.new(_SECRET_KEY, signed, hashlib.sha256).digest()).decode()
    if not valid:
        signature = "invalid-signature"
    return {
        "svix-id": event_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v1,{signature}",
        "Content-Type": "application/json",
    }


async def test_resend_send_retries_only_transient_and_uses_idempotency(monkeypatch):
    calls = _install_resend_mock(monkeypatch, [(500, {"error": "transient"}), (200, {"id": "msg_retry"})])
    result = await mailer._resend_send(
        to="owner@example.com",
        subject="Reset your A.R.M.X AI password",
        html_body="<p>reset</p>",
        text_body="reset",
        idempotency_key="idem-key-123456",
    )
    assert result.ok is True
    assert result.provider_message_id == "msg_retry"
    assert result.attempts == 2
    assert len(calls) == 2
    assert calls[0]["url"] == "https://api.resend.com/emails"
    assert calls[0]["headers"]["authorization"] == "Bearer re_test_key_1234567890"
    assert calls[0]["headers"]["idempotency-key"] == calls[1]["headers"]["idempotency-key"] == "idem-key-123456"
    assert calls[0]["json"]["from"] == "A.R.M.X AI <no-reply@armx.example>"
    assert calls[0]["json"]["to"] == ["owner@example.com"]
    assert "html" in calls[0]["json"] and "text" in calls[0]["json"]
    assert not hasattr(mailer, "smtplib")


async def test_resend_send_does_not_retry_invalid_request(monkeypatch):
    calls = _install_resend_mock(monkeypatch, [(422, {"error": "invalid_payload"})])
    result = await mailer._resend_send(
        to="owner@example.com",
        subject="Invalid",
        html_body="<p>invalid</p>",
        text_body="invalid",
        idempotency_key="idem-invalid-123456",
    )
    assert result.ok is False
    assert result.attempts == 1
    assert len(calls) == 1
    assert "HTTP 422" in result.error


async def test_register_verification_cooldown_policy_and_single_use(client, monkeypatch):
    calls = _install_resend_mock(monkeypatch, [(200, {"id": "msg_verify"})])
    client.cookies.clear()
    payload = {
        "email": "new@example.com",
        "password": STRONG_PASSWORD,
        "confirm_password": STRONG_PASSWORD,
        "full_name": "New Tester",
        "terms_accepted": True,
        "remember_me": True,
    }
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    assert "access_token" in response.json()
    set_cookies = "\n".join(response.headers.get_list("set-cookie"))
    assert settings.ACCESS_COOKIE_NAME in set_cookies
    assert settings.REFRESH_COOKIE_NAME in set_cookies
    assert "httponly" in set_cookies.lower()
    assert "samesite=lax" in set_cookies.lower()
    assert "re_test_key" not in response.text

    user = await _one(select(User).where(User.email == "new@example.com"))
    assert user is not None
    assert user.role == "user"
    assert user.is_verified is False
    assert user.display_name == "New Tester"

    row = await _one(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
    assert row is not None
    assert row.token_hash and not row.token_hash.startswith("ev_")
    assert row.used_at is None
    assert "ev_" not in row.token_hash

    delivery = await _wait_for_delivery("email_verification", "accepted")
    assert delivery.provider_message_id == "msg_verify"
    assert delivery.status == "accepted"
    assert delivery.delivered_at is None
    assert delivery.attempts == 1
    await _wait_for_captures(calls, 1)
    link, token = _link(calls, 0, "verify-email")
    assert link.startswith("https://armx.example/verify-email?token=")
    html_body = calls[0]["json"]["html"]
    text_body = calls[0]["json"]["text"]
    assert "CONTROL INTELLIGENCE" in html_body or "Control Intelligence" in html_body
    assert "expires in 24 hours" in html_body
    assert "Security notice" in html_body
    assert link in html_body
    assert link in text_body
    assert "never share verification links, passwords or api keys" in text_body.lower()
    assert STRONG_PASSWORD not in html_body and STRONG_PASSWORD not in text_body
    assert "re_test_key" not in html_body and "re_test_key" not in text_body

    resend = await client.post("/api/auth/resend-verification", json={"email": "new@example.com"})
    assert resend.status_code == 202
    assert resend.json()["message"] == GENERIC_VERIFICATION
    assert await _scalar(select(func.count(EmailVerificationToken.id))) == 1
    assert await _scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.purpose == "email_verification")) == 1

    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    gated = await client.get("/api/auth/me")
    assert gated.status_code == 403
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)

    verified = await client.post("/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    assert (await _one(select(User).where(User.id == user.id))).is_verified is True
    assert (await client.get("/api/auth/me")).status_code == 200
    reused = await client.post("/api/auth/verify-email", json={"token": token})
    assert reused.status_code == 400
    assert "already used" in reused.json()["detail"]
    legacy_get = await client.get(f"/api/auth/verify-email?token={token}")
    assert legacy_get.status_code == 400


async def test_forgot_password_hash_expiry_single_use_and_session_revocation(client, monkeypatch):
    calls = _install_resend_mock(
        monkeypatch,
        [(200, {"id": "msg_signup_verify"}), (200, {"id": "msg_reset"})],
    )
    await _signup(client, "owner@example.com")
    unknown = await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert unknown.status_code == 202
    assert unknown.json()["message"] == GENERIC_RESET

    forgot = await client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    assert forgot.status_code == 202
    assert forgot.json()["message"] == GENERIC_RESET
    second = await client.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    assert second.status_code == 202
    assert second.json()["message"] == GENERIC_RESET
    assert await _scalar(select(func.count(PasswordResetToken.id))) == 1
    assert await _scalar(select(func.count(EmailDelivery.id)).where(EmailDelivery.purpose == "password_reset")) == 1

    delivery = await _wait_for_delivery("password_reset", "accepted")
    assert delivery.provider_message_id == "msg_reset"
    assert delivery.status == "accepted"
    assert delivery.delivered_at is None
    await _wait_for_captures(calls, 2)
    link, token = _link(calls, 1, "reset-password")
    assert link.startswith("https://armx.example/reset-password?token=")
    assert "expires in 15 minutes" in calls[1]["json"]["html"]
    assert "Security notice" in calls[1]["json"]["html"]
    assert link in calls[1]["json"]["text"]
    assert "no password or api key" in calls[1]["json"]["text"].lower()

    reset_row = await _one(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    assert reset_row is not None
    assert reset_row.used_at is None
    assert "pr_" not in reset_row.token_hash
    assert token not in json.dumps(
        {
            "subject": delivery.subject,
            "idempotency_key": delivery.idempotency_key,
            "request_id": delivery.request_id,
        }
    )

    user = await _one(select(User).where(User.email == "owner@example.com"))
    expired_raw = new_opaque_token("pr_")
    async with SessionLocal() as session:
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(expired_raw),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await session.commit()
    expired = await client.post(
        "/api/auth/reset-password",
        json={"token": expired_raw, "password": "Expired1!x", "confirm_password": "Expired1!x"},
    )
    assert expired.status_code == 400
    assert "expired" in expired.json()["detail"].lower()

    client.cookies.clear()
    reset = await client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
    )
    assert reset.status_code == 204, reset.text
    assert (await client.get("/api/auth/me")).status_code == 401  # never auto-login

    sessions = await _all(select(Session).where(Session.user_id == user.id))
    assert sessions and all(session.revoked_at is not None for session in sessions)
    used = await _one(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    assert used is not None and used.used_at is not None
    fresh_user = await _one(select(User).where(User.id == user.id))
    assert verify_password(NEW_PASSWORD, fresh_user.password_hash)
    assert not verify_password(STRONG_PASSWORD, fresh_user.password_hash)

    old_login = await client.post("/api/auth/login", json={"email": "owner@example.com", "password": STRONG_PASSWORD})
    assert old_login.status_code == 401
    assert old_login.json()["detail"] == "Invalid email or password"
    new_login = await client.post("/api/auth/login", json={"email": "owner@example.com", "password": NEW_PASSWORD})
    assert new_login.status_code == 200, new_login.text

    reused = await client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "Another1!x", "confirm_password": "Another1!x"},
    )
    assert reused.status_code == 400
    assert "already used" in reused.json()["detail"]


async def test_not_configured_is_explicit_and_never_claims_delivery(client):
    tokens = await _signup(client, "local@example.com")
    assert tokens["access_token"]
    forgot = await client.post("/api/auth/forgot-password", json={"email": "local@example.com"})
    assert forgot.status_code == 202
    assert forgot.json()["message"] == GENERIC_RESET
    delivery = await _wait_for_delivery("password_reset", "not_configured")
    assert delivery.status == "not_configured"
    assert not delivery.provider_message_id
    assert delivery.delivered_at is None
    assert "no real email was sent" in delivery.last_error
    outbox = Path("var/outbox.log")
    assert outbox.exists()
    assert "status=not_configured" in outbox.read_text(encoding="utf-8")
    assert not hasattr(mailer, "smtplib")


async def test_webhook_signature_dedupe_terminal_status_and_admin_ledger(
    client, monkeypatch, auth_headers, admin_headers
):
    calls = _install_resend_mock(
        monkeypatch,
        [(200, {"id": "msg_owner_verify"}), (200, {"id": "msg_ledger"})],
        webhook_secret=_WEBHOOK_SECRET,
    )
    await _signup(client, "ledger@example.com")
    forgot = await client.post("/api/auth/forgot-password", json={"email": "ledger@example.com"})
    assert forgot.status_code == 202
    await _wait_for_delivery("password_reset", "accepted")
    await _wait_for_captures(calls, 2)
    assert calls[1]["json"]["html"].count("https://armx.example/reset-password?token=") >= 1

    raw = json.dumps({"type": "email.delivered", "data": {"email_id": "msg_ledger"}}).encode()
    unconfigured_headers = _signed_headers(raw, "evt_unconfigured")
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", "")
    unconfigured = await client.post("/api/webhooks/resend", content=raw, headers=unconfigured_headers)
    assert unconfigured.status_code == 503
    monkeypatch.setattr(settings, "RESEND_WEBHOOK_SECRET", _WEBHOOK_SECRET)

    forged = await client.post("/api/webhooks/resend", content=raw, headers=_signed_headers(raw, "evt_forged", valid=False))
    assert forged.status_code == 401
    old = await client.post(
        "/api/webhooks/resend",
        content=raw,
        headers=_signed_headers(raw, "evt_old", timestamp=int(time.time()) - 600),
    )
    assert old.status_code == 401
    assert await _scalar(select(func.count(EmailDeliveryEvent.id))) == 0

    delivered = await client.post("/api/webhooks/resend", content=raw, headers=_signed_headers(raw, "evt_delivered"))
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["outcome"] == "matched"
    delivery = await _one(select(EmailDelivery).where(EmailDelivery.provider_message_id == "msg_ledger"))
    assert delivery is not None
    assert delivery.status == "delivered"
    assert delivery.delivered_at is not None

    duplicate = await client.post("/api/webhooks/resend", content=raw, headers=_signed_headers(raw, "evt_delivered"))
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate"
    assert await _scalar(select(func.count(EmailDeliveryEvent.id))) == 1

    bounce_raw = json.dumps({"type": "email.bounced", "data": {"email_id": "msg_ledger", "bounce": {"type": "hard"}}}).encode()
    bounced = await client.post("/api/webhooks/resend", content=bounce_raw, headers=_signed_headers(bounce_raw, "evt_bounce"))
    assert bounced.status_code == 200
    assert bounced.json()["outcome"] == "matched"
    bounced_delivery = await _one(select(EmailDelivery).where(EmailDelivery.provider_message_id == "msg_ledger"))
    assert bounced_delivery.status == "bounced"
    assert bounced_delivery.failed_at is not None
    assert await _scalar(select(func.count(EmailDeliveryEvent.id))) == 2

    client.cookies.clear()
    assert (await client.get("/api/admin/email-deliveries")).status_code == 401
    assert (await client.get("/api/admin/email-deliveries", headers=auth_headers)).status_code == 403
    ledger = await client.get("/api/admin/email-deliveries", headers=admin_headers)
    assert ledger.status_code == 200, ledger.text
    body = ledger.json()
    assert body["event_count"] >= 2
    assert any(item["provider_message_id"] == "msg_ledger" for item in body["items"])
    assert "accepted (API request accepted, not delivered)" in body["status_legend"]
    assert "re_test_key" not in ledger.text
    assert "pr_" not in ledger.text and "ev_" not in ledger.text


async def test_public_config_flags_never_expose_secrets(client, monkeypatch):
    _install_resend_mock(monkeypatch, webhook_secret=_WEBHOOK_SECRET)
    response = await client.get("/api/config")
    assert response.status_code == 200
    features = response.json()["features"]
    assert features["resend_email"] is True
    assert features["resend_webhooks"] is True
    assert features["password_reset_ttl_minutes"] == 15
    assert features["email_resend_cooldown_seconds"] == 60
    assert features["http_only_cookies"] is True
    assert "re_test_key" not in response.text
    assert "RESEND_API_KEY" not in response.text
    assert "RESEND_FROM_EMAIL" not in response.text


def test_production_requires_resend_and_https_base_url():
    common = {
        "_env_file": None,
        "ENV": "production",
        "JWT_SECRET": "production-jwt-secret-that-is-long-enough-123456",
        "DATABASE_URL": "sqlite+aiosqlite:////tmp/armx-production-guard.db",
        "LLM_SECRETS_KEY": "JqYW-wqmgANnnAzqtxW3Fe0E-cBZEmJJgO43Vfzhz74=",
        "WEB_ORIGIN": "https://armx.example",
        "APP_BASE_URL": "https://armx.example",
        "REQUIRE_TURSO_IN_PRODUCTION": False,
        "AUTO_CREATE_TABLES": False,
        "DEBUG": False,
    }
    with pytest.raises(RuntimeError, match="RESEND_API_KEY"):
        Settings(**common, RESEND_API_KEY="", RESEND_FROM_EMAIL="")
    with pytest.raises(RuntimeError, match="https://"):
        http_base = dict(common)
        http_base["APP_BASE_URL"] = "http://armx.example"
        Settings(
            **http_base,
            RESEND_API_KEY="re_production_test_key_123456",
            RESEND_FROM_EMAIL="A.R.M.X AI <no-reply@armx.example>",
        )
    good = Settings(
        **common,
        RESEND_API_KEY="re_production_test_key_123456",
        RESEND_FROM_EMAIL="A.R.M.X AI <no-reply@armx.example>",
    )
    assert good.resend_configured is True
    assert good.auth_base_url.startswith("https://")


async def test_remember_me_changes_session_ttl_and_duplicate_registration_is_generic(client, monkeypatch):
    _install_resend_mock(monkeypatch, [(200, {"id": "msg_remember"})])
    client.cookies.clear()
    payload = {
        "email": "remember@example.com",
        "password": STRONG_PASSWORD,
        "confirm_password": STRONG_PASSWORD,
        "full_name": "Remember Tester",
        "terms_accepted": True,
        "remember_me": False,
    }
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201
    user = await _one(select(User).where(User.email == "remember@example.com"))
    short_sessions = await _all(select(Session).where(Session.user_id == user.id))
    assert short_sessions
    short_ttl = (as_utc(short_sessions[0].expires_at) - as_utc(short_sessions[0].created_at)).total_seconds()
    assert 0 < short_ttl <= settings.SESSION_REFRESH_TTL_HOURS * 3600 + 60

    duplicate = await client.post("/api/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert "Could not create the account" in duplicate.json()["detail"]
    assert "already exists" not in duplicate.json()["detail"].lower()

    long_login = await client.post(
        "/api/auth/login",
        json={"email": "remember@example.com", "password": STRONG_PASSWORD, "remember_me": True},
    )
    assert long_login.status_code == 200, long_login.text
    sessions = await _all(select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)))
    long_session = max(sessions, key=lambda row: as_utc(row.created_at))
    long_ttl = (as_utc(long_session.expires_at) - as_utc(long_session.created_at)).total_seconds()
    assert long_ttl > 24 * 3600


async def test_resend_provider_failure_is_logged_as_failed_not_delivered(client, monkeypatch):
    # Sign up before Resend is configured so only the password-reset call is mocked.
    await _signup(client, "failure@example.com")
    _install_resend_mock(monkeypatch, [(422, {"error": "invalid_payload"})])
    forgot = await client.post("/api/auth/forgot-password", json={"email": "failure@example.com"})
    assert forgot.status_code == 202
    assert forgot.json()["message"] == GENERIC_RESET
    delivery = await _wait_for_delivery("password_reset", "failed")
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert not delivery.provider_message_id
    assert delivery.delivered_at is None
    assert "HTTP 422" in delivery.last_error
    assert await _scalar(
        select(func.count(AuditEvent.id)).where(AuditEvent.action == "email.failed")
    ) >= 1
