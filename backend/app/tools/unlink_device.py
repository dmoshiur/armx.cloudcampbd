"""unlink_device (HIGH) - requires the password the DEVICE OWNER set at pairing."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.db import utcnow
from app.models import DeviceStatus, DeviceUnlinkEvent, LinkedDevice
from app.registry import RiskTier, ToolContext, ToolResult, tool
from app.security.tickets import UNLINK_TICKET, spend_ticket


class UnlinkDeviceInput(BaseModel):
    device_name: str = Field(min_length=1, max_length=60)
    unlink_ticket: str = Field(
        min_length=8,
        max_length=200,
        description=(
            "Ticket issued by POST /api/devices/{id}/unlink/verify after the device owner entered "
            "the unlink password. The password itself must never be passed to the assistant."
        ),
    )


@tool(
    name="unlink_device",
    description=(
        "Disable a device link. Requires a ticket minted on the device after its owner entered the "
        "unlink password - administrators and VIPs cannot override this. HIGH risk."
    ),
    risk=RiskTier.HIGH,
    input_model=UnlinkDeviceInput,
    scopes=("device:link", "owner_device"),
    confirm=True,
    rate_limit_per_minute=3,
    category="devices",
)
async def unlink_device(ctx: ToolContext, payload: UnlinkDeviceInput) -> ToolResult:
    rows = (
        await ctx.db.execute(
            LinkedDevice.__table__.select().where(
                LinkedDevice.owner_id == ctx.user.id,
                LinkedDevice.name == payload.device_name,
                LinkedDevice.status == DeviceStatus.ACTIVE.value,
            )
        )
    ).all()
    if not rows:
        return ToolResult(ok=False, error=f"No active linked device named '{payload.device_name}'")
    if len(rows) > 1:
        return ToolResult(ok=False, error="More than one device has that name; pass a unique name.")

    device = await ctx.db.get(LinkedDevice, rows[0].id)
    valid = await spend_ticket(
        ctx.db, kind=UNLINK_TICKET, user_id=ctx.user.id, token=payload.unlink_ticket, subject=device.id
    )
    if not valid:
        return ToolResult(
            ok=False,
            error=(
                "Invalid or expired ticket. Open the device page in A.R.M.X and enter the unlink "
                "password there - the assistant never handles that password."
            ),
        )

    device.status = DeviceStatus.REVOKED.value
    device.device_token_hash = None
    device.persistent_notification = False
    ctx.db.add(
        DeviceUnlinkEvent(
            device_id=device.id,
            actor_id=ctx.user.id,
            reason="unlink requested through assistant with owner-verified ticket",
            password_verified=True,
            ip_address=ctx.ip_address,
        )
    )
    await ctx.db.commit()
    return ToolResult(
        ok=True,
        data={"device_id": device.id, "name": device.name, "unlinked_at": utcnow().isoformat()},
        message=f"{device.name} is unlinked. Commands can no longer reach it.",
    )
