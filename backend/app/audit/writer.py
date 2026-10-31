"""Append-only, hash-chained audit writer.

Each entry hashes the previous entry's hash, so silently editing or deleting a
row breaks verification (``verify_chain``). The writer never updates or deletes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc, utcnow
from app.models import AuditEvent, User

GENESIS = "0" * 64
# Bump only with a migration plan: the digest covers historical rows, so changing
# the shape of the signed body invalidates every existing entry.
DIGEST_VERSION = 2


def _ts(value) -> str:
    """Stable timestamp representation.

    SQLite returns naive datetimes; hashing the raw ISO form would break the chain.
    Always sign/verify as naive-UTC with fixed microsecond precision.
    """
    aware = as_utc(value)
    return aware.replace(tzinfo=None).isoformat(timespec="microseconds")


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


async def audit(
    db: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    tool_name: str = "",
    risk_tier: str = "",
    status: str = "ok",
    target: str = "",
    detail: dict[str, Any] | None = None,
    ip_address: str = "",
    user_agent: str = "",
    _commit: bool = True,
) -> AuditEvent:
    prev = (
        await db.execute(select(AuditEvent).order_by(AuditEvent.ts.desc(), AuditEvent.id.desc()).limit(1))
    ).scalar_one_or_none()
    prev_hash = prev.entry_hash if prev else GENESIS
    event = AuditEvent(
        ts=utcnow(),
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else "",
        actor_role=actor.role if actor else "",
        action=action,
        tool_name=tool_name,
        risk_tier=risk_tier,
        target=target[:200],
        status=status,
        ip_address=ip_address,
        user_agent=user_agent[:400],
        detail=json.dumps(detail or {}, default=str)[:8000],
        prev_hash=prev_hash,
    )
    body = {
        "v": DIGEST_VERSION,
        "ts": _ts(event.ts),
        "actor_id": event.actor_id,
        "action": event.action,
        "tool": event.tool_name,
        "target": event.target,
        "status": event.status,
        "detail": event.detail,
        "prev": prev_hash,
    }
    event.entry_hash = _digest(body)
    db.add(event)
    if _commit:
        await db.commit()
    return event


async def verify_chain(db: AsyncSession, limit: int = 5000) -> dict[str, Any]:
    rows = (
        await db.execute(select(AuditEvent).order_by(AuditEvent.ts.asc(), AuditEvent.id.asc()).limit(limit))
    ).scalars().all()
    prev = GENESIS
    for i, row in enumerate(rows):
        body = {
            "v": DIGEST_VERSION,
            "ts": _ts(row.ts),
            "actor_id": row.actor_id,
            "action": row.action,
            "tool": row.tool_name,
            "target": row.target,
            "status": row.status,
            "detail": row.detail,
            "prev": prev,
        }
        if row.prev_hash != prev or row.entry_hash != _digest(body):
            return {"ok": False, "broken_at": i, "event_id": row.id, "checked": i + 1}
        prev = row.entry_hash
    return {"ok": True, "checked": len(rows)}
