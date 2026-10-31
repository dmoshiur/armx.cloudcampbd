"""Admin: users, tool toggles, audit log, kill-switch, read-only device view."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit, verify_chain
from app.core.db import get_db
from app.core.deps import client_ip, require_admin
from app.models import (
    Approval,
    AuditEvent,
    GeneratedProject,
    LinkedDevice,
    Session,
    ToolDefinition,
    ToolUserOverride,
    User,
)
from app.registry import registry
from app.security import kill_switch_engaged, set_kill_switch

router = APIRouter(prefix="/admin", tags=["admin"])


class RoleUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|vip|user)$")
    is_active: bool | None = None


class ToolToggle(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    enabled: bool


class UserToolToggle(ToolToggle):
    user_id: str = Field(min_length=8, max_length=32)


class KillSwitchUpdate(BaseModel):
    engaged: bool


@router.get("/overview")
async def overview(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    users = (await db.execute(select(func.count(User.id)))).scalar_one()
    active_users = (await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))).scalar_one()
    devices = (await db.execute(select(func.count(LinkedDevice.id)))).scalar_one()
    linked = (
        await db.execute(select(func.count(LinkedDevice.id)).where(LinkedDevice.status == "active"))
    ).scalar_one()
    approvals_pending = (
        await db.execute(select(func.count(Approval.id)).where(Approval.status == "pending"))
    ).scalar_one()
    events = (await db.execute(select(func.count(AuditEvent.id)))).scalar_one()
    projects = (await db.execute(select(func.count(GeneratedProject.id)))).scalar_one()
    sessions = (await db.execute(select(func.count(Session.id)).where(Session.revoked_at.is_(None)))).scalar_one()

    return {
        "users": users,
        "active_users": active_users,
        "devices": devices,
        "linked_devices": linked,
        "pending_approvals": approvals_pending,
        "audit_events": events,
        "generated_projects": projects,
        "active_sessions": sessions,
        "kill_switch": "on" if await kill_switch_engaged(db) else "off",
        "tools": {"total": len(registry.all()), "enabled": len(registry.all())},
    }


@router.get("/users")
async def list_users(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    return {
        "total": total,
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "role": u.role,
                "is_active": u.is_active,
                "is_verified": u.is_verified,
                "created_at": u.created_at.isoformat(),
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "locked": bool(u.locked_until),
            }
            for u in rows
        ],
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: RoleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.role and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot demote your own admin account")
    if payload.role:
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="You cannot disable your own account")
        user.is_active = payload.is_active
        if not payload.is_active:
            sessions = (
                await db.execute(select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)))
            ).scalars().all()
            from datetime import datetime, timezone

            for s in sessions:
                s.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(
        db,
        action="admin.user_updated",
        actor=admin,
        target=user.id,
        detail={"role": user.role, "is_active": user.is_active},
        ip_address=client_ip(request),
    )
    return {"id": user.id, "role": user.role, "is_active": user.is_active}


@router.get("/tools")
async def list_tools(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    definitions = {
        d.name: d for d in (await db.execute(select(ToolDefinition))).scalars().all()
    }
    out = []
    for spec in registry.all():
        d = definitions.get(spec.name)
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "risk": spec.risk.value,
                "category": spec.category,
                "scopes": list(spec.scopes),
                "confirm_required": spec.confirm or spec.risk.needs_approval,
                "rate_limit_per_minute": spec.rate_limit_per_minute,
                "enabled_global": d.enabled_global if d else True,
            }
        )
    return out


@router.patch("/tools")
async def toggle_tool(
    payload: ToolToggle,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if registry.get(payload.name) is None:
        raise HTTPException(status_code=404, detail="Unknown tool")
    row = (
        await db.execute(select(ToolDefinition).where(ToolDefinition.name == payload.name))
    ).scalar_one_or_none()
    if row is None:
        spec = registry.get(payload.name)
        row = ToolDefinition(**spec.definition_row(), enabled_global=payload.enabled)
        db.add(row)
    else:
        row.enabled_global = payload.enabled
    await db.commit()
    await audit(
        db,
        action="admin.tool_toggled",
        actor=admin,
        tool_name=payload.name,
        status="ok" if payload.enabled else "disabled",
        detail={"enabled": payload.enabled},
        ip_address=client_ip(request),
    )
    return {"name": payload.name, "enabled_global": payload.enabled}


@router.patch("/tools/user")
async def toggle_user_tool(
    payload: UserToolToggle,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if registry.get(payload.name) is None:
        raise HTTPException(status_code=404, detail="Unknown tool")
    if await db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    row = (
        await db.execute(
            select(ToolUserOverride).where(
                ToolUserOverride.user_id == payload.user_id, ToolUserOverride.tool_name == payload.name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(ToolUserOverride(user_id=payload.user_id, tool_name=payload.name, enabled=payload.enabled))
    else:
        row.enabled = payload.enabled
    await db.commit()
    await audit(
        db,
        action="admin.user_tool_toggled",
        actor=admin,
        tool_name=payload.name,
        target=payload.user_id,
        detail={"enabled": payload.enabled},
        ip_address=client_ip(request),
    )
    return {"user_id": payload.user_id, "name": payload.name, "enabled": payload.enabled}


@router.get("/audit")
async def audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str = Query(default="", max_length=80),
    status_filter: str = Query(default="", alias="status", max_length=24),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(AuditEvent).order_by(AuditEvent.ts.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if status_filter:
        stmt = stmt.where(AuditEvent.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(select(func.count(AuditEvent.id)))).scalar_one()
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "ts": e.ts.isoformat(),
                "actor_email": e.actor_email,
                "actor_role": e.actor_role,
                "action": e.action,
                "tool": e.tool_name,
                "risk": e.risk_tier,
                "target": e.target,
                "status": e.status,
                "ip_address": e.ip_address,
                "detail": json.loads(e.detail or "{}"),
                "entry_hash": e.entry_hash,
            }
            for e in rows
        ],
    }


@router.get("/audit/verify")
async def audit_verify(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await verify_chain(db)


@router.post("/kill-switch")
async def update_kill_switch(
    payload: KillSwitchUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await set_kill_switch(db, engaged=payload.engaged, actor_id=admin.id)
    await audit(
        db,
        action="admin.kill_switch",
        actor=admin,
        status="engaged" if payload.engaged else "released",
        detail={"engaged": payload.engaged},
        ip_address=client_ip(request),
    )
    return {"kill_switch": "on" if payload.engaged else "off"}


@router.get("/devices")
async def all_devices(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Read-only device view. Admins cannot unlink or command another user's device."""
    rows = (
        await db.execute(
            select(LinkedDevice, User.email).join(User, User.id == LinkedDevice.owner_id).order_by(LinkedDevice.created_at.desc())
        )
    ).all()
    out = []
    for device, email in rows:
        out.append(
            {
                "id": device.id,
                "name": device.name,
                "platform": device.platform,
                "status": device.status,
                "owner_email": email,
                "capabilities": [c for c in (device.capabilities or "").split(",") if c],
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                "read_only": True,
            }
        )
    return out


@router.get("/approvals")
async def all_approvals(
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(select(Approval).order_by(Approval.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "tool": a.tool_name,
            "risk": a.risk_tier,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
            "expires_at": a.expires_at.isoformat(),
            "action_hash": a.action_hash,
        }
        for a in rows
    ]
