"""Audit chain integrity, admin role gates, and cross-account (IDOR) checks."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit import audit, verify_chain
from app.models import AuditEvent, Conversation, User


async def test_audit_chain_is_hash_linked(db, user_tokens):
    user = (await db.execute(select(User).where(User.email == "user@example.com"))).scalar_one()
    for i in range(5):
        await audit(db, action=f"test.event{i}", actor=user, detail={"i": i})
    result = await verify_chain(db)
    assert result["ok"] is True
    # signup/login events are audited too, so the chain is strictly longer than 5.
    assert result["checked"] >= 5

    rows = (await db.execute(select(AuditEvent).order_by(AuditEvent.ts.asc()))).scalars().all()
    for prev, cur in zip(rows, rows[1:]):
        assert cur.prev_hash == prev.entry_hash


async def test_audit_chain_detects_tampering(db, user_tokens):
    user = (await db.execute(select(User).where(User.email == "user@example.com"))).scalar_one()
    for i in range(3):
        await audit(db, action=f"test.event{i}", actor=user)
    rows = (await db.execute(select(AuditEvent).order_by(AuditEvent.ts.asc()))).scalars().all()
    rows[1].detail = '{"tampered": true}'
    await db.commit()
    result = await verify_chain(db)
    assert result["ok"] is False


async def test_admin_endpoints_require_admin(client, auth_headers):
    for path in ("/api/admin/overview", "/api/admin/users", "/api/admin/audit", "/api/admin/devices"):
        assert (await client.get(path, headers=auth_headers)).status_code == 403
        assert (await client.get(path)).status_code == 401


async def test_admin_overview(client, admin_headers):
    resp = await client.get("/api/admin/overview", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["users"] >= 1
    assert body["kill_switch"] in {"on", "off"}


async def test_admin_cannot_demote_self(client, admin_headers, admin_tokens):
    me = await client.get("/api/auth/me", headers=admin_headers)
    resp = await client.patch(f"/api/admin/users/{me.json()['id']}", headers=admin_headers, json={"role": "user"})
    assert resp.status_code == 400


async def test_admin_user_tool_toggle_requires_real_user(client, admin_headers):
    resp = await client.patch(
        "/api/admin/tools/user",
        headers=admin_headers,
        json={"user_id": "0" * 32, "name": "health_status", "enabled": False},
    )
    assert resp.status_code == 404


async def test_conversation_is_not_readable_by_another_user(client, admin_headers):
    tokens = await client.post(
        "/api/auth/signup",
        json={"email": "victim@example.com", "password": "Sup3rSecret!", "display_name": "V"},
    )
    victim_headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}
    chat = await client.post("/api/assistant/chat", headers=victim_headers, json={"message": "check system health"})
    conv_id = chat.json()["conversation_id"]

    # Even an admin cannot read another user's conversation through the user API.
    resp = await client.get(f"/api/assistant/conversations/{conv_id}", headers=admin_headers)
    assert resp.status_code == 404
    assert (await client.get(f"/api/projects", headers=admin_headers)).json() == []


async def test_media_is_owner_scoped(client, auth_headers):
    import io

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00"
        b"\x00IEND\xaeB`\x82"
    )
    up = await client.post(
        "/api/media/upload", headers=auth_headers, files={"file": ("a.png", io.BytesIO(png), "image/png")}
    )
    assert up.status_code == 201
    asset_id = up.json()["asset_id"]
    assert (await client.get(f"/api/media/{asset_id}", headers=auth_headers)).status_code == 200

    other = await client.post(
        "/api/auth/signup", json={"email": "other@example.com", "password": "Sup3rSecret!", "display_name": "O"}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await client.get(f"/api/media/{asset_id}", headers=other_headers)).status_code == 404


async def test_upload_rejects_non_images(client, auth_headers):
    import io

    resp = await client.post(
        "/api/media/upload",
        headers=auth_headers,
        files={"file": ("evil.svg", io.BytesIO(b"<svg onload=alert(1)>"), "image/svg+xml")},
    )
    assert resp.status_code == 415
