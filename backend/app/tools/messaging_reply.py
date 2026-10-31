"""messaging_reply - WhatsApp/Messenger reply with dynamic risk.

MEDIUM when the contact is pre-approved with auto_send enabled (the owner already
vetted the thread); HIGH for anyone else. The platform never discovers or messages
contacts the owner has not added.
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from pydantic import BaseModel, Field

from app.integrations import messaging
from app.models import MessagingProfile
from app.registry import RiskTier, ToolContext, ToolResult, tool


class MessagingInput(BaseModel):
    channel: Literal["whatsapp", "messenger"] = "whatsapp"
    contact: str = Field(
        min_length=3, max_length=40,
        description="E.164 phone (whatsapp) or PSID (messenger) from the saved contact list",
    )
    message: str = Field(min_length=1, max_length=1200)


async def _resolve_risk(db, user, args: dict) -> RiskTier:
    contact = str(args.get("contact", "")).strip()
    channel = str(args.get("channel", "whatsapp"))
    profile = (
        await db.execute(
            select(MessagingProfile).where(
                MessagingProfile.user_id == user.id,
                MessagingProfile.channel == channel,
                MessagingProfile.contact_id == contact,
            )
        )
    ).scalar_one_or_none()
    if profile is not None and profile.auto_send:
        return RiskTier.MEDIUM
    return RiskTier.HIGH


@tool(
    name="messaging_reply",
    description=(
        "Reply on WhatsApp or Messenger to a saved contact. MEDIUM risk for pre-approved contacts "
        "with auto-send, HIGH for everyone else. Never messages an unsaved contact."
    ),
    risk=RiskTier.HIGH,
    input_model=MessagingInput,
    scopes=("messaging:send",),
    confirm=True,
    rate_limit_per_minute=10,
    dry_run_supported=True,
    category="messaging",
    risk_resolver=_resolve_risk,
)
async def messaging_reply(ctx: ToolContext, payload: MessagingInput) -> ToolResult:
    profile = (
        await ctx.db.execute(
            select(MessagingProfile).where(
                MessagingProfile.user_id == ctx.user.id,
                MessagingProfile.channel == payload.channel,
                MessagingProfile.contact_id == payload.contact,
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        return ToolResult(
            ok=False,
            error=(
                "Unknown contact. Add the person to your contact list (with their consent) before "
                "the assistant can message them."
            ),
        )

    if ctx.dry_run:
        return ToolResult(
            ok=True,
            data={"channel": payload.channel, "to": payload.contact, "dry_run": True, "preview": payload.message[:200]},
        )

    sender = messaging.send_whatsapp if payload.channel == "whatsapp" else messaging.send_messenger
    result = await sender(payload.contact, payload.message)
    if not result.get("ok"):
        return ToolResult(ok=False, error=str(result.get("error", "send failed"))[:300])
    return ToolResult(
        ok=True,
        data={**result, "contact_name": profile.display_name or payload.contact},
        message=f"Message sent to {profile.display_name or payload.contact} on {payload.channel}.",
    )
