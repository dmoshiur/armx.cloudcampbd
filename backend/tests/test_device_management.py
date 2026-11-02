from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AuditEvent, DeviceAppUsage
from tests.test_devices import _pair


def _device_headers(paired: dict) -> dict[str, str]:
    return {
        "X-Device-Id": paired["device"]["id"],
        "X-Device-Token": paired["device_token"],
    }


async def test_policy_is_staged_for_local_passcode_approval(client, vip_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    device_headers = _device_headers(paired)

    update = await client.put(
        f"/api/devices/{device_id}/management/policy",
        headers=vip_headers,
        json={
            "kiosk_enabled": True,
            "launcher_enabled": True,
            "usage_telemetry_enabled": True,
            "allowed_packages": ["com.android.chrome"],
            "restrictions": ["no_add_users", "no_unknown_sources"],
        },
    )
    assert update.status_code == 200, update.text
    policy = update.json()
    assert policy["pending_local_approval"] is True
    assert policy["local_approval_required"] is True
    assert "ai.armx.managed" in policy["allowed_packages"]

    commands = await client.get(f"/api/devices/{device_id}/commands", headers=device_headers)
    pending = [item for item in commands.json() if item["command"] == "apply_management_policy"]
    assert pending
    assert pending[0]["visible_to_user"] is True
    assert pending[0]["payload"]["requires_owner_passcode"] is True

    device_policy = await client.get(
        f"/api/devices/{device_id}/management/policy/device", headers=device_headers
    )
    assert device_policy.json()["last_applied_version"] == 0

    ack = await client.post(
        f"/api/devices/{device_id}/management/policy/ack",
        headers=device_headers,
        json={"policy_version": policy["policy_version"], "status": "applied", "error": ""},
    )
    assert ack.status_code == 200
    assert ack.json()["pending_local_approval"] is False
    assert ack.json()["last_applied_version"] == policy["policy_version"]


async def test_usage_telemetry_is_owner_opt_in_and_aggregate_only(client, vip_headers, db):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    device_headers = _device_headers(paired)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    item = {
        "package_name": "com.android.chrome",
        "foreground_seconds": 321,
        "launches": 4,
        "window_start": (now - timedelta(hours=1)).isoformat(),
        "window_end": now.isoformat(),
    }

    disabled = await client.post(
        f"/api/devices/{device_id}/management/usage",
        headers=device_headers,
        json={"items": [item]},
    )
    assert disabled.status_code == 403

    await client.put(
        f"/api/devices/{device_id}/management/policy",
        headers=vip_headers,
        json={
            "kiosk_enabled": False,
            "launcher_enabled": False,
            "usage_telemetry_enabled": True,
            "allowed_packages": ["ai.armx.managed"],
            "restrictions": [],
        },
    )
    upload = await client.post(
        f"/api/devices/{device_id}/management/usage",
        headers=device_headers,
        json={"items": [item]},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json() == {"accepted": 1}

    owner_view = await client.get(
        f"/api/devices/{device_id}/management/usage?days=1", headers=vip_headers
    )
    assert owner_view.status_code == 200
    assert owner_view.json()["content_captured"] is False
    reported = owner_view.json()["items"][0]
    assert reported["package_name"] == item["package_name"]
    assert reported["foreground_seconds"] == 321
    assert reported["launches"] == 4
    row = (await db.execute(select(DeviceAppUsage))).scalar_one()
    assert row.package_name == "com.android.chrome"
    assert row.foreground_seconds == 321


async def test_voice_consent_is_visible_revocable_and_audited(client, vip_headers, db):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    device_headers = _device_headers(paired)

    requested = await client.post(
        f"/api/devices/{device_id}/consent-sessions",
        headers=vip_headers,
        json={"kind": "voice", "scopes": ["microphone", "speaker"]},
    )
    assert requested.status_code == 201, requested.text
    session_id = requested.json()["id"]
    assert requested.json()["status"] == "requested"

    hidden = await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/decision",
        headers=device_headers,
        json={"decision": "consent", "visible_indicator": False, "system_consent": False},
    )
    assert hidden.status_code == 400
    consented = await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/decision",
        headers=device_headers,
        json={"decision": "consent", "visible_indicator": True, "system_consent": False},
    )
    assert consented.status_code == 200
    assert consented.json()["status"] == "active"
    assert consented.json()["visible_indicator"] is True

    ended = await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/device-end",
        headers=device_headers,
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    actions = (await db.execute(select(AuditEvent.action))).scalars().all()
    assert "device.consent_requested" in actions
    assert "device.consent_granted" in actions
    assert "device.consent_session_ended" in actions


async def test_admin_management_visibility_is_read_only_and_audited(
    client, vip_headers, admin_headers, db
):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    await client.put(
        f"/api/devices/{device_id}/management/policy",
        headers=vip_headers,
        json={
            "kiosk_enabled": True,
            "launcher_enabled": True,
            "usage_telemetry_enabled": False,
            "allowed_packages": ["ai.armx.managed"],
            "restrictions": ["no_safe_boot"],
        },
    )

    view = await client.get(f"/api/admin/devices/{device_id}/management", headers=admin_headers)
    assert view.status_code == 200
    assert view.json()["read_only"] is True
    assert "usage_detail" in view.json()
    assert "items" not in view.json()
    actions = (await db.execute(select(AuditEvent.action))).scalars().all()
    assert "admin.device_management_viewed" in actions
