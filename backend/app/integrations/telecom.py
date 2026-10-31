"""Call control + app launching on the owner's own device.

The backend never talks to the telecom stack directly: it queues an explicit,
user-visible command that the paired Flutter app polls and executes with the
Android Telecom / package-manager APIs. Call recording, silent interception and
call/SMS forwarding do not exist anywhere in this codebase.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeviceCommand, DeviceStatus, LinkedDevice

ALLOWED_COMMANDS = {
    "answer_call",
    "decline_call",
    "place_call",
    "open_app",
    "set_alarm",
    "cancel_alarm",
    "lock_pc",
    "unlock_pc",
    "speak",
    "start_screen_share",
    "end_screen_share",
    "ring",
}

# Packages the owner can allow on their own device. Anything else is refused by the app.
DEFAULT_ALLOWED_PACKAGES = ("com.whatsapp", "com.android.chrome", "com.spotify.music", "org.telegram.messenger")


def status() -> dict[str, Any]:
    return {
        "provider": "device_link",
        "configured": True,
        "mode": "queued",  # commands are delivered when the paired device polls
        "detail": "Call/app control runs on the paired Android device, never in the cloud.",
    }


async def queue_command(
    db: AsyncSession,
    *,
    user_id: str,
    device: LinkedDevice,
    command: str,
    payload: dict[str, Any],
) -> DeviceCommand:
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"Unsupported device command: {command}")
    if device.status != DeviceStatus.ACTIVE.value:
        raise ValueError("Device link is not active")

    caps = {c.strip() for c in (device.capabilities or "").split(",") if c.strip()}
    if command in {"answer_call", "decline_call", "place_call"} and "calls" not in caps:
        raise ValueError("This device link has not granted call control")
    if command == "open_app" and "app_launch" not in caps:
        raise ValueError("This device link has not granted app launching")
    if command in {"set_alarm", "cancel_alarm"} and "alarm" not in caps:
        raise ValueError("This device link has not granted alarm control")

    cmd = DeviceCommand(
        device_id=device.id,
        issued_by=user_id,
        command=command,
        payload=json.dumps(payload, default=str)[:4000],
        visible_to_user=True,  # always visible on the device - no silent mode exists
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


async def pick_device(db: AsyncSession, user_id: str, device_name: str | None = None) -> LinkedDevice | None:
    stmt = select(LinkedDevice).where(
        LinkedDevice.owner_id == user_id, LinkedDevice.status == DeviceStatus.ACTIVE.value
    )
    devices = (await db.execute(stmt)).scalars().all()
    if not devices:
        return None
    if device_name:
        for d in devices:
            if d.name.lower() == device_name.lower():
                return d
        return None
    # Prefer the most recently seen device.
    return max(devices, key=lambda d: d.last_seen_at or d.created_at)


async def pending_commands(db: AsyncSession, device_id: str, limit: int = 20) -> list[DeviceCommand]:
    rows = (
        await db.execute(
            select(DeviceCommand)
            .where(DeviceCommand.device_id == device_id, DeviceCommand.status.in_(("queued", "delivered")))
            .order_by(DeviceCommand.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def acknowledge(db: AsyncSession, device_id: str, command_id: str, status: str, result: dict[str, Any]) -> bool:
    cmd = await db.get(DeviceCommand, command_id)
    if cmd is None or cmd.device_id != device_id:
        return False
    cmd.status = status if status in {"delivered", "done", "failed"} else "done"
    cmd.result = json.dumps(result, default=str)[:2000]
    from app.core.db import utcnow

    cmd.acknowledged_at = utcnow()
    await db.commit()
    return True
