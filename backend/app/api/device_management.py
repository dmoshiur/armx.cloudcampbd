"""Owner-controlled Android management, aggregate telemetry and session consent."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import _owned_device, device_auth
from app.audit import audit
from app.core.db import as_utc, get_db, utcnow
from app.core.deps import AuthContext, client_ip, get_auth_context, require_admin
from app.core.mirror import MAX_FRAME_BYTES, mirror_frames
from app.integrations import telecom
from app.models import (
    DeviceAppUsage,
    DeviceConsentSession,
    DeviceStatus,
    LinkedDevice,
    ManagedDevicePolicy,
    User,
)

router = APIRouter(prefix="/devices", tags=["managed devices"])
admin_router = APIRouter(prefix="/admin/devices", tags=["admin", "managed devices"])

PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
MANAGEMENT_CAPABILITY = "management"
SUPPORTED_RESTRICTIONS = {"no_add_users", "no_unknown_sources", "no_safe_boot"}


class ManagedPolicyUpdate(BaseModel):
    kiosk_enabled: bool = False
    launcher_enabled: bool = False
    usage_telemetry_enabled: bool = False
    allowed_packages: list[str] = Field(default_factory=list, max_length=200)
    restrictions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("allowed_packages")
    @classmethod
    def _packages(cls, values: list[str]) -> list[str]:
        cleaned = sorted(set(values + ["ai.armx.managed"]))
        if any(not PACKAGE_PATTERN.fullmatch(value) for value in cleaned):
            raise ValueError("allowed_packages contains an invalid Android package name")
        return cleaned

    @field_validator("restrictions")
    @classmethod
    def _restrictions(cls, values: list[str]) -> list[str]:
        unknown = set(values) - SUPPORTED_RESTRICTIONS
        if unknown:
            raise ValueError(f"unsupported restrictions: {sorted(unknown)}")
        return sorted(set(values))


class PolicyAck(BaseModel):
    policy_version: int = Field(ge=1)
    status: Literal["applied", "rejected", "failed"]
    error: str = Field(default="", max_length=500)


class UsageItem(BaseModel):
    package_name: str = Field(min_length=3, max_length=255)
    foreground_seconds: int = Field(ge=0, le=604800)
    launches: int = Field(ge=0, le=100000)
    window_start: datetime
    window_end: datetime

    @field_validator("package_name")
    @classmethod
    def _package(cls, value: str) -> str:
        if not PACKAGE_PATTERN.fullmatch(value):
            raise ValueError("invalid Android package name")
        return value

    @model_validator(mode="after")
    def _window(self) -> "UsageItem":
        start, end = as_utc(self.window_start), as_utc(self.window_end)
        if start is None or end is None or start >= end:
            raise ValueError("usage window must have a start before its end")
        if end - start > timedelta(days=7):
            raise ValueError("usage window cannot exceed 7 days")
        if end > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("usage window cannot be in the future")
        return self


class UsageBatch(BaseModel):
    items: list[UsageItem] = Field(min_length=1, max_length=200)


class ConsentRequest(BaseModel):
    kind: Literal["screen_share", "voice"]
    scopes: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _valid_scopes(self) -> "ConsentRequest":
        allowed = {"screen_share": {"screen"}, "voice": {"microphone", "speaker"}}[self.kind]
        scopes = set(self.scopes) or allowed
        if not scopes.issubset(allowed):
            raise ValueError(f"invalid scopes for {self.kind}: {sorted(scopes - allowed)}")
        self.scopes = sorted(scopes)
        return self


class ConsentDecision(BaseModel):
    decision: Literal["consent", "decline"]
    visible_indicator: bool
    system_consent: bool = False
    note: str = Field(default="", max_length=300)


def _capabilities(device: LinkedDevice) -> set[str]:
    return {value.strip() for value in (device.capabilities or "").split(",") if value.strip()}


def _require_managed(device: LinkedDevice) -> None:
    if device.status != DeviceStatus.ACTIVE.value or device.platform != "android":
        raise HTTPException(status_code=400, detail="An active Android device link is required")
    if MANAGEMENT_CAPABILITY not in _capabilities(device):
        raise HTTPException(status_code=403, detail="This device link did not grant management capability")


def _policy_out(policy: ManagedDevicePolicy | None) -> dict[str, Any]:
    if policy is None:
        return {
            "configured": False,
            "policy_version": 0,
            "kiosk_enabled": False,
            "launcher_enabled": False,
            "usage_telemetry_enabled": False,
            "allowed_packages": ["ai.armx.managed"],
            "restrictions": [],
            "local_approval_required": True,
            "last_applied_version": 0,
            "last_applied_at": None,
            "last_error": "",
        }
    return {
        "configured": True,
        "policy_version": policy.policy_version,
        "kiosk_enabled": policy.kiosk_enabled,
        "launcher_enabled": policy.launcher_enabled,
        "usage_telemetry_enabled": policy.usage_telemetry_enabled,
        "allowed_packages": json.loads(policy.allowed_packages),
        "restrictions": json.loads(policy.restrictions),
        "local_approval_required": policy.local_approval_required,
        "last_applied_version": policy.last_applied_version,
        "last_applied_at": policy.last_applied_at.isoformat() if policy.last_applied_at else None,
        "last_error": policy.last_error,
        "pending_local_approval": policy.last_applied_version < policy.policy_version,
    }


async def _get_policy(db: AsyncSession, device_id: str) -> ManagedDevicePolicy | None:
    return (
        await db.execute(select(ManagedDevicePolicy).where(ManagedDevicePolicy.device_id == device_id))
    ).scalar_one_or_none()


@router.get("/{device_id}/management/policy")
async def owner_policy(
    device_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    _require_managed(device)
    return _policy_out(await _get_policy(db, device.id))


@router.put("/{device_id}/management/policy")
async def update_owner_policy(
    device_id: str,
    payload: ManagedPolicyUpdate,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    _require_managed(device)
    policy = await _get_policy(db, device.id)
    if policy is None:
        policy = ManagedDevicePolicy(device_id=device.id, updated_by=ctx.user.id)
        db.add(policy)
        await db.flush()
    else:
        policy.policy_version += 1
    policy.kiosk_enabled = payload.kiosk_enabled
    policy.launcher_enabled = payload.launcher_enabled
    policy.usage_telemetry_enabled = payload.usage_telemetry_enabled
    policy.allowed_packages = json.dumps(payload.allowed_packages)
    policy.restrictions = json.dumps(payload.restrictions)
    policy.local_approval_required = True
    policy.updated_by = ctx.user.id
    policy.last_error = ""
    await db.commit()
    await telecom.queue_command(
        db,
        user_id=ctx.user.id,
        device=device,
        command="apply_management_policy",
        payload={**_policy_out(policy), "requires_owner_passcode": True},
    )
    await audit(
        db,
        action="device.management_policy_updated",
        actor=ctx.user,
        target=device.id,
        detail={"policy_version": policy.policy_version, "local_approval_required": True},
        ip_address=client_ip(request),
    )
    return _policy_out(policy)


@router.get("/{device_id}/management/policy/device")
async def device_policy(
    device_id: str,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    _require_managed(device)
    return _policy_out(await _get_policy(db, device.id))


@router.post("/{device_id}/management/policy/ack")
async def acknowledge_policy(
    device_id: str,
    payload: PolicyAck,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    policy = await _get_policy(db, device.id)
    if policy is None or payload.policy_version != policy.policy_version:
        raise HTTPException(status_code=409, detail="Policy version is stale or unknown")
    if payload.status == "applied":
        policy.last_applied_version = payload.policy_version
        policy.last_applied_at = utcnow()
        policy.last_error = ""
    else:
        policy.last_error = payload.error or f"Local owner {payload.status} the policy"
    await db.commit()
    await audit(
        db,
        action=f"device.management_policy_{payload.status}",
        target=device.id,
        status="ok" if payload.status == "applied" else "denied",
        detail={"policy_version": payload.policy_version, "source": "device"},
    )
    return _policy_out(policy)


@router.post("/{device_id}/management/usage")
async def upload_usage(
    device_id: str,
    payload: UsageBatch,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    policy = await _get_policy(db, device.id)
    if policy is None or not policy.usage_telemetry_enabled or "usage" not in _capabilities(device):
        raise HTTPException(status_code=403, detail="The owner has not enabled usage telemetry")
    written = 0
    for item in payload.items:
        start, end = as_utc(item.window_start), as_utc(item.window_end)
        existing = (
            await db.execute(
                select(DeviceAppUsage).where(
                    DeviceAppUsage.device_id == device.id,
                    DeviceAppUsage.package_name == item.package_name,
                    DeviceAppUsage.window_start == start,
                    DeviceAppUsage.window_end == end,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                DeviceAppUsage(
                    device_id=device.id,
                    package_name=item.package_name,
                    foreground_seconds=item.foreground_seconds,
                    launch_count=item.launches,
                    window_start=start,
                    window_end=end,
                )
            )
        else:
            existing.foreground_seconds = item.foreground_seconds
            existing.launch_count = item.launches
            existing.reported_at = utcnow()
        written += 1
    await db.commit()
    await audit(
        db,
        action="device.usage_reported",
        target=device.id,
        detail={"aggregates": written, "source": "device", "content_captured": False},
    )
    return {"accepted": written}


@router.get("/{device_id}/management/usage")
async def owner_usage(
    device_id: str,
    days: int = 7,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    if days < 1 or days > 30:
        raise HTTPException(status_code=400, detail="days must be between 1 and 30")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(DeviceAppUsage)
            .where(DeviceAppUsage.device_id == device.id, DeviceAppUsage.window_end >= cutoff)
            .order_by(DeviceAppUsage.window_end.desc())
            .limit(2000)
        )
    ).scalars().all()
    return {
        "permission_scoped": True,
        "content_captured": False,
        "items": [
            {
                "package_name": row.package_name,
                "foreground_seconds": row.foreground_seconds,
                "launches": row.launch_count,
                "window_start": row.window_start.isoformat(),
                "window_end": row.window_end.isoformat(),
            }
            for row in rows
        ],
    }


@router.post("/{device_id}/consent-sessions", status_code=201)
async def request_consent_session(
    device_id: str,
    payload: ConsentRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    required_capability = "screen_share" if payload.kind == "screen_share" else "voice"
    if required_capability not in _capabilities(device):
        raise HTTPException(status_code=403, detail=f"Device link did not grant {required_capability}")
    current = (
        await db.execute(
            select(DeviceConsentSession).where(
                DeviceConsentSession.device_id == device.id,
                DeviceConsentSession.kind == payload.kind,
                DeviceConsentSession.status.in_(("requested", "active")),
            )
        )
    ).scalar_one_or_none()
    if current and as_utc(current.expires_at) <= datetime.now(timezone.utc):
        current.status = "expired"
        current.ended_at = utcnow()
        current.ended_by = "expiry"
        await db.commit()
        if current.kind == "screen_share":
            await mirror_frames.remove(current.id)
        current = None
    if current:
        raise HTTPException(status_code=409, detail="A consent request or active session already exists")
    session = DeviceConsentSession(
        device_id=device.id,
        requested_by=ctx.user.id,
        kind=payload.kind,
        status="requested",
        scopes=json.dumps(payload.scopes),
        visible_indicator=True,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    command = "request_screen_share" if payload.kind == "screen_share" else "request_voice_session"
    await telecom.queue_command(
        db,
        user_id=ctx.user.id,
        device=device,
        command=command,
        payload={"session_id": session.id, "scopes": payload.scopes, "expires_at": session.expires_at.isoformat()},
    )
    await audit(
        db,
        action="device.consent_requested",
        actor=ctx.user,
        target=device.id,
        detail={"session_id": session.id, "kind": session.kind, "scopes": payload.scopes},
        ip_address=client_ip(request),
    )
    return _session_out(session)


def _session_out(session: DeviceConsentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "device_id": session.device_id,
        "kind": session.kind,
        "status": session.status,
        "scopes": json.loads(session.scopes),
        "visible_indicator": session.visible_indicator,
        "requested_at": session.requested_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "consented_at": session.consented_at.isoformat() if session.consented_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "ended_by": session.ended_by,
        "device_note": session.device_note,
    }


@router.post("/{device_id}/consent-sessions/{session_id}/decision")
async def device_consent_decision(
    device_id: str,
    session_id: str,
    payload: ConsentDecision,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    session = await db.get(DeviceConsentSession, session_id)
    if session is None or session.device_id != device.id:
        raise HTTPException(status_code=404, detail="Consent session not found")
    if session.status != "requested":
        raise HTTPException(status_code=409, detail="Consent session is no longer awaiting a decision")
    if as_utc(session.expires_at) < datetime.now(timezone.utc):
        session.status = "expired"
        session.ended_at = utcnow()
        session.ended_by = "expiry"
        await db.commit()
        raise HTTPException(status_code=410, detail="Consent request expired")
    if payload.decision == "consent" and not payload.visible_indicator:
        raise HTTPException(status_code=400, detail="An active visible indicator is mandatory")
    if payload.decision == "consent" and session.kind == "screen_share" and not payload.system_consent:
        raise HTTPException(status_code=400, detail="Android MediaProjection consent is mandatory")
    session.status = "active" if payload.decision == "consent" else "declined"
    session.visible_indicator = payload.visible_indicator
    session.device_note = payload.note
    if payload.decision == "consent":
        session.consented_at = utcnow()
        # The original expiry is the response deadline. Active capture remains
        # bounded as an additional fail-safe even if neither peer sends an end.
        session.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    else:
        session.ended_at = utcnow()
        session.ended_by = "device"
    await db.commit()
    await audit(
        db,
        action=f"device.consent_{'granted' if payload.decision == 'consent' else 'declined'}",
        target=device.id,
        status="ok" if payload.decision == "consent" else "denied",
        detail={"session_id": session.id, "kind": session.kind, "source": "device"},
    )
    return _session_out(session)


@router.post("/{device_id}/consent-sessions/{session_id}/frame", status_code=202)
async def upload_mirror_frame(
    device_id: str,
    session_id: str,
    request: Request,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    session = await db.get(DeviceConsentSession, session_id)
    if (
        session is None
        or session.device_id != device.id
        or session.kind != "screen_share"
        or session.status != "active"
        or not session.visible_indicator
    ):
        raise HTTPException(status_code=409, detail="A visible, consented screen-share session is not active")
    if as_utc(session.expires_at) <= datetime.now(timezone.utc):
        session.status = "expired"
        session.ended_at = utcnow()
        session.ended_by = "expiry"
        await db.commit()
        await mirror_frames.remove(session.id)
        raise HTTPException(status_code=410, detail="Screen-share session expired")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "image/jpeg":
        raise HTTPException(status_code=415, detail="Mirror frames must use image/jpeg")
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > MAX_FRAME_BYTES):
        raise HTTPException(status_code=413, detail="Mirror frame is too large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_FRAME_BYTES:
            raise HTTPException(status_code=413, detail="Mirror frame is too large")
        chunks.append(chunk)
    try:
        frame = await mirror_frames.put(session.id, b"".join(chunks))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"accepted": True, "sequence": frame.sequence, "captured_at": frame.captured_at.isoformat()}


@router.get("/{device_id}/consent-sessions/{session_id}/frame")
async def latest_mirror_frame(
    device_id: str,
    session_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    device = await _owned_device(db, ctx.user, device_id)
    session = await db.get(DeviceConsentSession, session_id)
    if session is None or session.device_id != device.id or session.kind != "screen_share":
        raise HTTPException(status_code=404, detail="Screen-share session not found")
    if session.status != "active" or not session.visible_indicator:
        raise HTTPException(status_code=409, detail="Screen sharing is not active")
    if as_utc(session.expires_at) <= datetime.now(timezone.utc):
        session.status = "expired"
        session.ended_at = utcnow()
        session.ended_by = "expiry"
        await db.commit()
        await mirror_frames.remove(session.id)
        raise HTTPException(status_code=410, detail="Screen-share session expired")
    frame = await mirror_frames.get(session.id)
    if frame is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return Response(
        content=frame.content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Frame-Sequence": str(frame.sequence),
            "X-Frame-Captured-At": frame.captured_at.isoformat(),
        },
    )


@router.post("/{device_id}/consent-sessions/{session_id}/end")
async def end_owner_session(
    device_id: str,
    session_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await _owned_device(db, ctx.user, device_id)
    session = await db.get(DeviceConsentSession, session_id)
    if session is None or session.device_id != device.id:
        raise HTTPException(status_code=404, detail="Consent session not found")
    await _end_session(db, session, ctx.user.id)
    command = "end_screen_share" if session.kind == "screen_share" else "end_voice_session"
    await telecom.queue_command(db, user_id=ctx.user.id, device=device, command=command, payload={"session_id": session.id})
    await audit(
        db,
        action="device.consent_session_ended",
        actor=ctx.user,
        target=device.id,
        detail={"session_id": session.id, "kind": session.kind},
        ip_address=client_ip(request),
    )
    return _session_out(session)


@router.post("/{device_id}/consent-sessions/{session_id}/device-end")
async def end_device_session(
    device_id: str,
    session_id: str,
    device: LinkedDevice = Depends(device_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match this device")
    session = await db.get(DeviceConsentSession, session_id)
    if session is None or session.device_id != device.id:
        raise HTTPException(status_code=404, detail="Consent session not found")
    await _end_session(db, session, "device")
    await audit(
        db,
        action="device.consent_session_ended",
        target=device.id,
        detail={"session_id": session.id, "kind": session.kind, "source": "device"},
    )
    return _session_out(session)


async def _end_session(db: AsyncSession, session: DeviceConsentSession, ended_by: str) -> None:
    if session.status not in {"active", "requested"}:
        return
    session.status = "ended"
    session.ended_at = utcnow()
    session.ended_by = ended_by
    await db.commit()
    if session.kind == "screen_share":
        await mirror_frames.remove(session.id)


@router.get("/{device_id}/consent-sessions")
async def list_owner_sessions(
    device_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    device = await _owned_device(db, ctx.user, device_id)
    sessions = (
        await db.execute(
            select(DeviceConsentSession)
            .where(DeviceConsentSession.device_id == device.id)
            .order_by(DeviceConsentSession.requested_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [_session_out(session) for session in sessions]


@admin_router.get("/{device_id}/management")
async def admin_management_visibility(
    device_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    device = await db.get(LinkedDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    policy = await _get_policy(db, device.id)
    sessions = (
        await db.execute(
            select(DeviceConsentSession)
            .where(DeviceConsentSession.device_id == device.id)
            .order_by(DeviceConsentSession.requested_at.desc())
            .limit(20)
        )
    ).scalars().all()
    await audit(
        db,
        action="admin.device_management_viewed",
        actor=admin,
        target=device.id,
        detail={"read_only": True},
        ip_address=client_ip(request),
    )
    return {
        "read_only": True,
        "device_id": device.id,
        "owner_id": device.owner_id,
        "capabilities": sorted(_capabilities(device)),
        "policy": _policy_out(policy),
        "consent_sessions": [_session_out(session) for session in sessions],
        "usage_detail": "Owner-visible only; admin aggregate access is intentionally unavailable.",
    }
