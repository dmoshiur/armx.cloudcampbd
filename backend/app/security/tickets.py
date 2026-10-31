"""Single-use, short-lived tickets for out-of-band confirmations.

Example: the linked-device unlink password is verified by the device owner in the
API (never by the model). That call returns a ticket; ``unlink_device`` may then be
driven by the assistant without the password ever entering the conversation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import as_utc
from app.core.security import hash_token, new_opaque_token
from app.models import Ticket

UNLINK_TICKET = "device_unlink"
DEVICE_PROOF_TICKET = "device_unlock_proof"


async def issue_ticket(
    db: AsyncSession, *, kind: str, user_id: str, subject: str = "", ttl_seconds: int = 120
) -> str:
    token = new_opaque_token("tkt_")
    db.add(
        Ticket(
            kind=kind,
            user_id=user_id,
            subject=subject,
            token_hash=hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
    )
    await db.commit()
    return token


async def spend_ticket(db: AsyncSession, *, kind: str, user_id: str, token: str, subject: str | None = None) -> bool:
    row = (
        await db.execute(
            select(Ticket).where(Ticket.token_hash == hash_token(token or ""), Ticket.kind == kind)
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id or row.used_at is not None:
        return False
    if subject is not None and row.subject != subject:
        return False
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        return False
    row.used_at = datetime.now(timezone.utc)
    await db.commit()
    return True
