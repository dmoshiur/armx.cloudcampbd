"""Linked devices: consent-based pairing, owner-password unlink, visible commands.

Rules enforced in code, not just the UI:
* A link only activates after it is confirmed ON the device with the pairing code
  and a password chosen by the device owner.
* Unlinking requires that password. There is no admin/VIP override endpoint.
* Commands are always visible on the device; there is no silent mode.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.db import as_utc, get_db
from app.core.deps import AuthContext, get_auth_context, client_ip
from app.core.security import (
    constant_time_compare,
    hash_password,
    hash_token,
    new_opaque_token,
    rate_limiter,
    verify_password,
)
from app.integrations import telecom
from app.models import (
    DeviceStatus,
    DeviceUnlinkEvent,
    LinkedDevice,
    ScreenShareSession,
    User,
)
from app.security.tickets import DEVICE_PROOF_TICKET, UNLINK_TICKET, issue_ticket

router = APIRouter(prefix="/devices", tags=["devices"])

MAX_DEVICES = 10


class PairingRequestModel(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    platform: str = Field(default="android", pattern="^(android|desktop|watch)$")
    capabilities: list[str] = Field(default_factory=lambda: ["alarm", "app_launch", "state", "calls"])


class PairConfirmModel(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    unlink_password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=60)
    platform: str | None = Field(default=None, pattern="^(android|desktop|watch)$")
    capabilities: list[str] | None = None

    @field_validator("unlink_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if v.isdigit() or len(set(v)) < 4:
            raise ValueError("unlink password is too weak - use letters and digits")
        return v


class PasswordModel(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class TicketModel(BaseModel):
    ticket: str = Field(min_length=8, max_length=200)


def _device_out(device: LinkedDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.name,
        "platform": device.platform,
        "status": device.status,
        "capabilities": [c for c in (device.capabilities or "").split(",") if c],
        "persistent_notification": device.persistent_notification,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat(),
        # Never expose the unlink password hash.
    }


async def _owned_device(db: AsyncSession, user: User, device_id: str) -> LinkedDevice:
    device = await db.get(LinkedDevice, device_id)
    if device is None or device.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


# --------------------------------------------------------------------------
# listings
# --------------------------------------------------------------------------
@router.get("")
async def list_devices(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(LinkedDevice).where(LinkedDevice.owner_id == ctx.user.id).order_by(LinkedDevice.created_at.desc())
        )
    ).scalars().all()
    return [_device_out(d) for d in rows]


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------
@router.post("/pairing/request", status_code=201)
async def request_pairing(
    payload: PairingRequestModel,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Step 1 - the owner starts pairing from the web or the assistant."""
    if ctx.user.role == "user":
        raise HTTPException(status_code=403, detail="Device linking requires the VIP role")
    active = (
        await db.execute(select(LinkedDevice).where(LinkedDevice.owner_id == ctx.user.id))
    ).scalars().all()
    if len([d for d in active if d.status != DeviceStatus.REVOKED.value]) >= MAX_DEVICES:
        raise HTTPException(status_code=400, detail=f"Device limit reached ({MAX_DEVICES})")

    unknown = set(payload.capabilities) - {"alarm", "app_launch", "state", "calls", "speak"}
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported capabilities: {sorted(unknown)}")

    code = f"{secrets.randbelow(10**6):06d}"
    device = LinkedDevice(
        owner_id=ctx.user.id,
        name=payload.name,
        platform=payload.platform,
        status=DeviceStatus.PENDING.value,
        pairing_code_hash=hash_token(code),
        pairing_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        unlink_password_hash="",
        capabilities=",".join(sorted(set(payload.capabilities))),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    await audit(db, action="device.pairing_requested", actor=ctx.user, target=device.id)
    return {
        "device": _device_out(device),
        "pairing_code": code,
        "expires_in_minutes": 10,
        "next_step": "Enter this code in the A.R.M.X app on the device and set an unlink password there.",
    }


@router.post("/pairing/confirm")
async def confirm_pairing(
    payload: PairConfirmModel,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Step 2 - confirmed ON the device. This is where the unlink password is set."""
    ok, _ = rate_limiter.hit(f"pairing:{ctx.user.id}", 10)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many attempts")

    code_hash = hash_token(payload.code)
    device = (
        await db.execute(select(LinkedDevice).where(LinkedDevice.pairing_code_hash == code_hash))
    ).scalar_one_or_none()
    if device is None or device.owner_id != ctx.user.id or device.status != DeviceStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Pairing code is invalid or already used")
    if as_utc(device.pairing_expires_at) is None or as_utc(device.pairing_expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Pairing code expired - start again")

    if payload.name:
        device.name = payload.name.strip()
    if payload.platform:
        device.platform = payload.platform
    if payload.capabilities is not None:
        allowed = {"alarm", "app_launch", "state", "calls", "speak"}
        unknown = set(payload.capabilities) - allowed
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unsupported capabilities: {sorted(unknown)}")
        device.capabilities = ",".join(sorted(set(payload.capabilities)))

    device.unlink_password_hash = hash_password(payload.unlink_password)
    device.status = DeviceStatus.ACTIVE.value
    device.pairing_completed_at = datetime.now(timezone.utc)
    device.pairing_code_hash = None
    device.persistent_notification = True
    device_token = new_opaque_token("dv_")
    device.device_token_hash = hash_token(device_token)
    device.ip_address = client_ip(request)
    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(device)

    await audit(
        db,
        action="device.paired",
        actor=ctx.user,
        target=device.id,
        ip_address=client_ip(request),
        detail={"name": device.name, "platform": device.platform, "capabilities": device.capabilities},
    )
    return {
        "device": _device_out(device),
        "device_token": device_token,
        "note": (
            "Store this token in secure storage on the device. The device must always show the "
            "persistent 'Linked' notification - there is no silent mode."
        ),
    }


# --------------------------------------------------------------------------
# unlink (owner password only)
# --------------------------------------------------------------------------
@router.post("/{device_id}/unlink/verify")
async def verify_unlink_password(
    device_id: str,
    payload: PasswordModel,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ok, _ = rate_limiter.hit(f"unlink:{ctx.user.id}", 5)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many attempts; wait a minute")

    device = await _owned_device(db, ctx.user, device_id)
    if device.status != DeviceStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail="Device is not actively linked")
    if not verify_password(payload.password, device.unlink_password_hash):
        await audit(
            db, action="device.unlink_denied", actor=ctx.user, target=device.id, status="denied",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=403, detail="Incorrect unlink password")

    ticket = await issue_ticket(db, kind=UNLINK_TICKET, user_id=ctx.user.id, subject=device.id, ttl_seconds=120)
    return {"ticket": ticket, "expires_in_seconds": 120}


@router.post("/{device_id}/unlink", status_code=204)
async def unlink_device(
    device_id: str,
    payload: TicketModel,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.security.tickets import spend_ticket

    device = await _owned_device(db, ctx.user, device_id)
    if not await spend_ticket(db, kind=UNLINK_TICKET, user_id=ctx.user.id, token=payload.ticket, subject=device.id):
        raise HTTPException(status_code=403, detail="Unlink ticket is invalid or expired")
    device.status = DeviceStatus.REVOKED.value
    device.device_token_hash = None
    device.persistent_notification = False
    db.add(
        DeviceUnlinkEvent(
            device_id=device.id,
            actor_id=ctx.user.id,
            reason="owner unlink",
            password_verified=True,
            ip_address=client_ip(request),
        )
    )
    await db.commit()
    await audit(db, action="device.unlinked", actor=ctx.user, target=device.id, ip_address=client_ip(request))
    return Response(status_code=204)


@router.get("/{device_id}/unlink-events")
async def unlink_events(
    device_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    device = await _owned_device(db, ctx.user, device_id)
    rows = (
        await db.execute(
            select(DeviceUnlinkEvent).where(DeviceUnlinkEvent.device_id == device.id).order_by(DeviceUnlinkEvent.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": e.id,
            "reason": e.reason,
            "password_verified": e.password_verified,
            "ip_address": e.ip_address,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


# --------------------------------------------------------------------------
# device-authenticated endpoints (native app)
# --------------------------------------------------------------------------
async def device_auth(
    x_device_id: str = Header(default="", alias="X-Device-Id"),
    x_device_token: str = Header(default="", alias="X-Device-Token"),
    db: AsyncSession = Depends(get_db),
) -> LinkedDevice:
    if not x_device_id or not x_device_token:
        raise HTTPException(status_code=401, detail="Device credentials required")
    device = await db.get(LinkedDevice, x_device_id)
    if device is None or device.status != DeviceStatus.ACTIVE.value or not device.device_token_hash:
        raise HTTPException(status_code=401, detail="Device is not linked")
    if not constant_time_compare(device.device_token_hash, hash_token(x_device_token)):
        raise HTTPException(status_code=401, detail="Device token rejected")
    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return device


@router.get("/{device_id}/commands")
async def poll_commands(
    device_id: str,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    rows = await telecom.pending_commands(db, device.id)
    out = []
    for cmd in rows:
        out.append(
            {
                "id": cmd.id,
                "command": cmd.command,
                "payload": json.loads(cmd.payload or "{}"),
                "visible_to_user": cmd.visible_to_user,
                "created_at": cmd.created_at.isoformat(),
            }
        )
        if cmd.status == "queued":
            cmd.status = "delivered"
    await db.commit()
    return out


@router.post("/{device_id}/commands/{command_id}/ack")
async def ack_command(
    device_id: str,
    command_id: str,
    payload: dict[str, Any],
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    status = str(payload.get("status", "done"))
    ok = await telecom.acknowledge(db, device.id, command_id, status, payload.get("result", {}))
    if not ok:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"ok": True}


@router.post("/{device_id}/notification")
async def update_notification(
    device_id: str,
    payload: dict[str, Any],
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """The persistent 'Linked' notification cannot be switched off - only acknowledged."""
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    from app.core.db import utcnow

    device.notification_ack_at = utcnow()
    device.persistent_notification = True
    await db.commit()
    return {"persistent_notification": True, "acknowledged_at": device.notification_ack_at.isoformat()}


@router.post("/{device_id}/unlock-proof")
async def mint_unlock_proof(
    device_id: str,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Called by the desktop client after its LOCAL biometric/PIN check succeeds."""
    if device.id != device_id or device.platform != "desktop":
        raise HTTPException(status_code=403, detail="Only the paired desktop device may mint this proof")
    ticket = await issue_ticket(
        db, kind=DEVICE_PROOF_TICKET, user_id=device.owner_id, subject=device.id, ttl_seconds=90
    )
    return {"proof_token": ticket, "expires_in_seconds": 90}


@router.post("/{device_id}/screen-share/start")
async def start_screen_share(
    device_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    if device.status != DeviceStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail="Device is not linked")
    existing = (
        await db.execute(
            select(ScreenShareSession).where(ScreenShareSession.device_id == device.id, ScreenShareSession.status == "active")
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A screen-share session is already active")

    session = ScreenShareSession(device_id=device.id, started_by=ctx.user.id, status="active")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    await telecom.queue_command(
        db, user_id=ctx.user.id, device=device, command="start_screen_share", payload={"session_id": session.id}
    )
    await audit(db, action="device.screen_share_started", actor=ctx.user, target=device.id)
    return {"session_id": session.id, "status": "active", "notice": "The device now shows a sharing indicator."}


@router.post("/{device_id}/screen-share/stop", status_code=204)
async def stop_screen_share(
    device_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> Response:
    device = await _owned_device(db, ctx.user, device_id)
    rows = (
        await db.execute(
            select(ScreenShareSession).where(ScreenShareSession.device_id == device.id, ScreenShareSession.status == "active")
        )
    ).scalars().all()
    from app.core.db import utcnow

    for s in rows:
        s.status = "ended"
        s.ended_at = utcnow()
        s.ended_by = ctx.user.id
    await db.commit()
    await telecom.queue_command(db, user_id=ctx.user.id, device=device, command="end_screen_share", payload={})
    await audit(db, action="device.screen_share_stopped", actor=ctx.user, target=device.id)
    return Response(status_code=204)


@router.get("/{device_id}/screen-share")
async def screen_share_status(
    device_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    session = (
        await db.execute(
            select(ScreenShareSession).where(ScreenShareSession.device_id == device.id, ScreenShareSession.status == "active")
        )
    ).scalar_one_or_none()
    return {
        "active": session is not None,
        "session_id": session.id if session else None,
        "started_at": session.started_at.isoformat() if session else None,
    }
