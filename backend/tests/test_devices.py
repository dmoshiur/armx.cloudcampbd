"""Linked devices: consent, owner-password unlink, no admin override, no silent commands."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceCommand, LinkedDevice, User


async def _pair(client, headers, name: str = "Bedroom Pixel", password: str = "DevicePass1!") -> dict:
    req = await client.post(
        "/api/devices/pairing/request",
        headers=headers,
        json={"name": name, "platform": "android", "capabilities": ["alarm", "app_launch", "state", "calls"]},
    )
    assert req.status_code == 201, req.text
    code = req.json()["pairing_code"]
    confirm = await client.post(
        "/api/devices/pairing/confirm",
        headers=headers,
        json={"code": code, "unlink_password": password},
    )
    assert confirm.status_code == 200, confirm.text
    return confirm.json()


async def test_pairing_requires_vip(client, auth_headers):
    resp = await client.post(
        "/api/devices/pairing/request",
        headers=auth_headers,
        json={"name": "Nope", "platform": "android", "capabilities": ["state"]},
    )
    assert resp.status_code == 403


async def test_pairing_needs_the_code_from_the_device(client, vip_headers):
    req = await client.post(
        "/api/devices/pairing/request",
        headers=vip_headers,
        json={"name": "Watch", "platform": "watch", "capabilities": ["alarm"]},
    )
    assert req.status_code == 201
    bad = await client.post(
        "/api/devices/pairing/confirm",
        headers=vip_headers,
        json={"code": "000000", "unlink_password": "DevicePass1!"},
    )
    assert bad.status_code == 400


async def test_pairing_rejects_weak_unlink_password(client, vip_headers):
    req = await client.post(
        "/api/devices/pairing/request",
        headers=vip_headers,
        json={"name": "Weak", "platform": "android", "capabilities": ["state"]},
    )
    code = req.json()["pairing_code"]
    resp = await client.post(
        "/api/devices/pairing/confirm",
        headers=vip_headers,
        json={"code": code, "unlink_password": "12345678"},
    )
    assert resp.status_code == 422


async def test_device_unlink_requires_owner_password(client, vip_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]

    wrong = await client.post(
        f"/api/devices/{device_id}/unlink/verify", headers=vip_headers, json={"password": "WrongPass1!"}
    )
    assert wrong.status_code == 403

    right = await client.post(
        f"/api/devices/{device_id}/unlink/verify", headers=vip_headers, json={"password": "DevicePass1!"}
    )
    assert right.status_code == 200
    ticket = right.json()["ticket"]

    done = await client.post(f"/api/devices/{device_id}/unlink", headers=vip_headers, json={"ticket": ticket})
    assert done.status_code == 204

    # Ticket is single use.
    again = await client.post(f"/api/devices/{device_id}/unlink", headers=vip_headers, json={"ticket": ticket})
    assert again.status_code == 403


async def test_admin_cannot_unlink_someone_elses_device(client, vip_headers, admin_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]

    resp = await client.post(
        f"/api/devices/{device_id}/unlink/verify", headers=admin_headers, json={"password": "DevicePass1!"}
    )
    # 404 rather than 403: an admin cannot even see another account's device as theirs.
    assert resp.status_code == 404

    admin_view = await client.get("/api/admin/devices", headers=admin_headers)
    assert admin_view.status_code == 200
    assert all(d["read_only"] is True for d in admin_view.json())


async def test_device_token_scopes_commands(client, vip_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    token = paired["device_token"]

    bad = await client.get(f"/api/devices/{device_id}/commands", headers={"X-Device-Id": device_id, "X-Device-Token": "nope"})
    assert bad.status_code == 401

    ok = await client.get(f"/api/devices/{device_id}/commands", headers={"X-Device-Id": device_id, "X-Device-Token": token})
    assert ok.status_code == 200


async def test_commands_always_visible_to_user(client, vip_headers, db, vip_tokens):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    from app.models import User as U

    user = (await db.execute(select(U).where(U.email == "vip@example.com"))).scalar_one()
    device = await db.get(LinkedDevice, device_id)
    from app.integrations import telecom

    cmd = await telecom.queue_command(
        db, user_id=user.id, device=device, command="set_alarm", payload={"time": "07:00"}
    )
    assert cmd.visible_to_user is True

    token = paired["device_token"]
    polled = await client.get(
        f"/api/devices/{device_id}/commands", headers={"X-Device-Id": device_id, "X-Device-Token": token}
    )
    assert polled.status_code == 200
    assert polled.json()[0]["command"] == "set_alarm"
    assert polled.json()[0]["visible_to_user"] is True


async def test_unsupported_command_is_refused(db, client, vip_headers):
    paired = await _pair(client, vip_headers)
    user = (await db.execute(select(User).where(User.email == "vip@example.com"))).scalar_one()
    device = await db.get(LinkedDevice, paired["device"]["id"])
    from app.integrations import telecom

    with pytest.raises(ValueError):
        await telecom.queue_command(db, user_id=user.id, device=device, command="record_call", payload={})


async def test_screen_share_is_flagged_and_stoppable(client, vip_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    start = await client.post(f"/api/devices/{device_id}/screen-share/start", headers=vip_headers)
    assert start.status_code == 200
    assert start.json()["status"] == "active"
    status = await client.get(f"/api/devices/{device_id}/screen-share", headers=vip_headers)
    assert status.json()["active"] is True
    stop = await client.post(f"/api/devices/{device_id}/screen-share/stop", headers=vip_headers)
    assert stop.status_code == 204
    status = await client.get(f"/api/devices/{device_id}/screen-share", headers=vip_headers)
    assert status.json()["active"] is False
