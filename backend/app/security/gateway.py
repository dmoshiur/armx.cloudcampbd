"""The Security Gateway.

Invariants enforced here (and nowhere else):

* Claude can *request* a tool; only the gateway ever invokes a handler.
* A globally- or per-user-disabled tool is blocked even if the model asks.
* The kill-switch halts every integration immediately, independent of the AI.
* Every MEDIUM/HIGH tool needs a single-use approval bound to a hash of
  tool + arguments + actor + session + expiry. Changing one argument
  invalidates the approval because the hash no longer matches.
* Rate limits are applied per user *and* per tool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import audit
from app.core.config import settings
from app.core.db import as_utc
from app.core.security import action_hash, hash_arguments, rate_limiter
from app.models import Approval, ApprovalStatus, SystemFlag, ToolDefinition, ToolUserOverride, User
from app.registry import (
    KILL_SWITCH_SAFE_TOOLS,
    RiskTier,
    ToolArgumentError,
    ToolContext,
    ToolResult,
    ToolSpec,
    registry,
)

KILL_SWITCH_KEY = "kill_switch"


class GatewayError(Exception):
    """Denied by policy. ``code`` is stable for clients."""

    def __init__(self, code: str, message: str, *, status_code: int = 403, extra: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}
        super().__init__(message)

    def payload(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.message, **self.extra}


@dataclass(slots=True)
class GatewayDecision:
    allowed: bool
    reason: str = ""
    needs_approval: bool = False
    effective_risk: RiskTier | None = None
    approval: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Kill-switch
# --------------------------------------------------------------------------
async def kill_switch_engaged(db: AsyncSession) -> bool:
    row = (await db.execute(select(SystemFlag).where(SystemFlag.key == KILL_SWITCH_KEY))).scalar_one_or_none()
    return bool(row and row.value == "on")


async def set_kill_switch(db: AsyncSession, *, engaged: bool, actor_id: str) -> None:
    row = (await db.execute(select(SystemFlag).where(SystemFlag.key == KILL_SWITCH_KEY))).scalar_one_or_none()
    if row is None:
        row = SystemFlag(key=KILL_SWITCH_KEY, value="on" if engaged else "off", updated_by=actor_id)
        db.add(row)
    else:
        row.value = "on" if engaged else "off"
        row.updated_by = actor_id
    await db.commit()


# --------------------------------------------------------------------------
# Enablement (global tool_definitions + per-user overrides)
# --------------------------------------------------------------------------
async def tool_enabled(db: AsyncSession, spec: ToolSpec, user: User) -> tuple[bool, str]:
    definition = (
        await db.execute(select(ToolDefinition).where(ToolDefinition.name == spec.name))
    ).scalar_one_or_none()
    if definition is not None and not definition.enabled_global:
        return False, "tool disabled by administrator"

    override = (
        await db.execute(
            select(ToolUserOverride).where(
                ToolUserOverride.user_id == user.id, ToolUserOverride.tool_name == spec.name
            )
        )
    ).scalar_one_or_none()
    if override is not None and not override.enabled:
        return False, "tool disabled for this account"

    # Scope enforcement: HIGH-risk device tools require a VIP/ADMIN account.
    if spec.risk is RiskTier.HIGH and "owner_device" in spec.scopes and user.role not in ("vip", "admin"):
        return False, "requires VIP account"

    if ("admin_only" in spec.scopes) and user.role != "admin":
        return False, "administrator only"

    return True, ""


def effective_rate_limit(spec: ToolSpec, definition: ToolDefinition | None) -> int:
    if definition is not None and definition.rate_limit_per_minute:
        return min(definition.rate_limit_per_minute, spec.rate_limit_per_minute)
    return min(spec.rate_limit_per_minute, settings.TOOL_RATE_LIMIT_PER_MINUTE)


# --------------------------------------------------------------------------
# Pre-flight check (used by the harness before asking for approval)
# --------------------------------------------------------------------------
async def preflight(
    db: AsyncSession, *, spec: ToolSpec, user: User, session_id: str, args: dict[str, Any]
) -> GatewayDecision:
    if spec.name not in KILL_SWITCH_SAFE_TOOLS and await kill_switch_engaged(db):
        return GatewayDecision(False, "kill-switch engaged: all integrations are halted")

    enabled, why = await tool_enabled(db, spec, user)
    if not enabled:
        return GatewayDecision(False, why)

    definition = (
        await db.execute(select(ToolDefinition).where(ToolDefinition.name == spec.name))
    ).scalar_one_or_none()
    limit = effective_rate_limit(spec, definition)
    ok, _remaining = rate_limiter.hit(f"tool:{user.id}:{spec.name}", limit)
    if not ok:
        return GatewayDecision(False, f"rate limit reached ({limit}/min) for {spec.name}")

    try:
        registry.validate_args(spec.name, args)
    except ToolArgumentError as exc:
        return GatewayDecision(False, f"invalid arguments: {exc.detail}")

    effective = await resolve_risk(db, spec, user, args)
    if effective.needs_approval:
        return GatewayDecision(True, "approval required", needs_approval=True, effective_risk=effective)
    return GatewayDecision(True, effective_risk=effective)


async def resolve_risk(db: AsyncSession, spec: ToolSpec, user: User, args: dict[str, Any]) -> RiskTier:
    """Static tier, unless the tool declares a dynamic (argument-dependent) tier."""
    if spec.risk_resolver is None:
        return spec.risk
    try:
        resolved = await spec.risk_resolver(db, user, args)
    except Exception:  # a broken resolver must fail closed, not open
        return RiskTier.HIGH
    # Never allow a resolver to weaken a HIGH declaration below MEDIUM.
    if spec.risk is RiskTier.HIGH and resolved is RiskTier.LOW:
        return RiskTier.MEDIUM
    return resolved


# --------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------
async def create_approval(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    spec: ToolSpec,
    args: dict[str, Any],
    run_id: str | None = None,
    ttl_seconds: int | None = None,
) -> Approval:
    ttl = ttl_seconds or settings.APPROVAL_TTL_SECONDS
    effective_risk = await resolve_risk(db, spec, user, args)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    a_hash = action_hash(
        tool=spec.name, args=args, actor_id=user.id, session_id=session_id, expires_at=expires_at
    )
    approval = Approval(
        user_id=user.id,
        session_id=session_id,
        run_id=run_id,
        tool_name=spec.name,
        risk_tier=effective_risk.value,
        args_json=json.dumps(args, sort_keys=True, default=str),
        args_hash=hash_arguments(args),
        action_hash=a_hash,
        expires_at=expires_at,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    await audit(
        db,
        action="approval.requested",
        actor=user,
        tool_name=spec.name,
        risk_tier=effective_risk.value,
        status="pending",
        detail={"approval_id": approval.id, "action_hash": a_hash, "args": args},
    )
    return approval


async def consume_approval(
    db: AsyncSession,
    *,
    approval_id: str,
    user: User,
    session_id: str,
    spec: ToolSpec,
    args: dict[str, Any],
) -> Approval:
    """Validate + burn an approval atomically-ish. Replay and arg-swap proof."""
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise GatewayError("approval_not_found", "Approval does not exist", status_code=404)
    if approval.user_id != user.id:
        raise GatewayError("approval_foreign", "Approval belongs to another account")
    if approval.session_id != session_id:
        raise GatewayError("approval_wrong_session", "Approval was issued for a different session")
    if approval.tool_name != spec.name:
        raise GatewayError("approval_wrong_tool", "Approval is for a different tool")
    if approval.status != ApprovalStatus.PENDING.value:
        raise GatewayError("approval_reused", f"Approval already {approval.status}")
    if as_utc(approval.expires_at) < datetime.now(timezone.utc):
        approval.status = ApprovalStatus.EXPIRED.value
        await db.commit()
        raise GatewayError("approval_expired", "Approval expired")

    expires_at = as_utc(approval.expires_at)
    expected = action_hash(
        tool=spec.name, args=args, actor_id=user.id, session_id=session_id, expires_at=expires_at
    )
    if expected != approval.action_hash:
        await audit(
            db,
            action="approval.hash_mismatch",
            actor=user,
            tool_name=spec.name,
            risk_tier=spec.risk.value,
            status="denied",
            detail={"approval_id": approval.id},
        )
        raise GatewayError(
            "approval_argument_mismatch",
            "Arguments changed since the approval was granted; request a new one",
        )

    approval.status = ApprovalStatus.CONSUMED.value
    approval.consumed_at = datetime.now(timezone.utc)
    await db.commit()
    return approval


async def deny_approval(db: AsyncSession, *, approval_id: str, user: User) -> None:
    approval = await db.get(Approval, approval_id)
    if approval is None or approval.user_id != user.id:
        raise GatewayError("approval_not_found", "Approval does not exist", status_code=404)
    approval.status = ApprovalStatus.DENIED.value
    await db.commit()
    await audit(
        db,
        action="approval.denied",
        actor=user,
        tool_name=approval.tool_name,
        risk_tier=approval.risk_tier,
        status="denied",
        detail={"approval_id": approval_id},
    )


# --------------------------------------------------------------------------
# Execute
# --------------------------------------------------------------------------
async def execute(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    approval_id: str | None = None,
    dry_run: bool = False,
    ip_address: str = "",
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    """The ONLY path from a tool request to a tool execution."""
    spec = registry.get(tool_name)
    if spec is None:
        raise GatewayError("unknown_tool", f"Unknown tool: {tool_name}", status_code=404)

    decision = await preflight(db, spec=spec, user=user, session_id=session_id, args=args)
    if not decision.allowed:
        await audit(
            db,
            action="tool.denied",
            actor=user,
            tool_name=tool_name,
            risk_tier=spec.risk.value,
            status="denied",
            detail={"reason": decision.reason, "args": args},
            ip_address=ip_address,
        )
        raise GatewayError("denied", decision.reason)

    effective_risk = decision.effective_risk or spec.risk
    if effective_risk.needs_approval and not dry_run:
        if not approval_id:
            raise GatewayError(
                "approval_required",
                f"{tool_name} is {effective_risk.value}-risk and needs explicit approval",
                extra={"tool": tool_name, "risk": effective_risk.value, "args": args},
            )
        await consume_approval(
            db, approval_id=approval_id, user=user, session_id=session_id, spec=spec, args=args
        )

    validated = registry.validate_args(tool_name, args)
    ctx = ToolContext(
        db=db,
        user=user,
        session_id=session_id,
        ip_address=ip_address,
        dry_run=dry_run or (spec.dry_run_supported and bool(args.get("dry_run"))),
        approval_id=approval_id,
        metadata=metadata or {},
    )

    try:
        result = await spec.handler(ctx, validated)
    except GatewayError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:500])

    await audit(
        db,
        action="tool.executed",
        actor=user,
        tool_name=tool_name,
        risk_tier=effective_risk.value,
        status="ok" if result.ok else "error",
        detail={"args": args, "dry_run": ctx.dry_run, "result": result.to_payload()},
        ip_address=ip_address,
    )
    return result
