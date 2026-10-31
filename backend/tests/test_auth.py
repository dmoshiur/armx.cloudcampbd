"""Auth: password policy, lockout, refresh rotation, reset tokens, enum safety."""
from __future__ import annotations

import pytest

from tests.conftest import _signup


async def test_health_reports_honest_state(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["planner"]["provider"] == "mock"
    assert body["tools"] == 21


async def test_signup_rejects_weak_password(client):
    resp = await client.post(
        "/api/auth/signup", json={"email": "weak@example.com", "password": "password123", "display_name": "W"}
    )
    assert resp.status_code == 422


async def test_signup_never_creates_admin(client, db):
    from sqlalchemy import select

    from app.models import User

    await _signup(client, "nobody@example.com")
    user = (await db.execute(select(User).where(User.email == "nobody@example.com"))).scalar_one()
    assert user.role == "user"


async def test_duplicate_signup_is_rejected(client):
    await _signup(client, "dupe@example.com")
    resp = await client.post(
        "/api/auth/signup",
        json={"email": "dupe@example.com", "password": "Sup3rSecret!", "display_name": "D"},
    )
    assert resp.status_code == 409


async def test_login_and_wrong_password(client):
    await _signup(client, "login@example.com")
    ok = await client.post("/api/auth/login", json={"email": "login@example.com", "password": "Sup3rSecret!"})
    assert ok.status_code == 200
    bad = await client.post("/api/auth/login", json={"email": "login@example.com", "password": "WrongPass1!"})
    assert bad.status_code == 401
    # Unknown user must produce the same response shape (no account enumeration).
    unknown = await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "WrongPass1!"})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == bad.json()["detail"]


async def test_lockout_after_repeated_failures(client):
    await _signup(client, "lock@example.com")
    for _ in range(5):
        await client.post("/api/auth/login", json={"email": "lock@example.com", "password": "Nope12345!"})
    resp = await client.post("/api/auth/login", json={"email": "lock@example.com", "password": "Sup3rSecret!"})
    assert resp.status_code == 429


async def test_refresh_rotates_and_reuse_revokes_family(client):
    tokens = await _signup(client, "rotate@example.com")
    first = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    second_refresh = first.json()["refresh_token"]
    assert second_refresh != tokens["refresh_token"]

    # Replaying the original (already rotated) token must fail and revoke everything.
    replay = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    after = await client.post("/api/auth/refresh", json={"refresh_token": second_refresh})
    assert after.status_code == 401


async def test_password_reset_flow_single_use(client, db):
    from sqlalchemy import select

    from app.models import PasswordResetToken, User

    await _signup(client, "reset@example.com")
    resp = await client.post("/api/auth/forgot-password", json={"email": "reset@example.com"})
    assert resp.status_code == 202

    # The raw token is only ever in the email; read the sidecar outbox written in dev mode.
    from pathlib import Path

    outbox = Path("var/outbox.log")
    assert outbox.exists()
    raw = outbox.read_text().strip().split("token=")[-1].split("\n")[0]
    assert raw

    new_password = "FreshSecret9!"
    ok = await client.post("/api/auth/reset-password", json={"token": raw, "password": new_password})
    assert ok.status_code == 204
    again = await client.post("/api/auth/reset-password", json={"token": raw, "password": "Another1!aaa"})
    assert again.status_code == 400

    login = await client.post("/api/auth/login", json={"email": "reset@example.com", "password": new_password})
    assert login.status_code == 200

    user = (await db.execute(select(User).where(User.email == "reset@example.com"))).scalar_one()
    row = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    ).scalar_one()
    assert row.used_at is not None


async def test_forgot_password_does_not_leak_account_existence(client):
    r1 = await client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    await _signup(client, "present@example.com")
    r2 = await client.post("/api/auth/forgot-password", json={"email": "present@example.com"})
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()


async def test_me_requires_valid_token(client, auth_headers):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers={"Authorization": "Bearer nope"})).status_code == 401
    ok = await client.get("/api/auth/me", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["email"] == "user@example.com"


async def test_logout_revokes_session(client, auth_headers):
    assert (await client.post("/api/auth/logout", headers=auth_headers)).status_code == 204
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401


async def test_change_password_revokes_other_sessions(client, user_tokens, auth_headers):
    resp = await client.post(
        "/api/auth/change-password",
        headers=auth_headers,
        json={"current_password": "Sup3rSecret!", "new_password": "BrandNew1!x"},
    )
    assert resp.status_code == 204
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401
