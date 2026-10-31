"""pc_lock (MEDIUM) - lock the owner's own desktop session."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool


class PcLockInput(BaseModel):
    device_name: str = Field(default="", max_length=80, description="Linked desktop device")


@tool(
    name="pc_lock",
    description="Lock the owner's own linked desktop session. The device shows the action.",
    risk=RiskTier.MEDIUM,
    input_model=PcLockInput,
    scopes=("device:desktop", "owner_device"),
    confirm=True,
    rate_limit_per_minute=10,
    category="device",
)
async def pc_lock(ctx: ToolContext, payload: PcLockInput) -> ToolResult:
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name or None)
    if device is None:
        return ToolResult(ok=False, error="No active linked desktop device")
    if device.platform != "desktop":
        return ToolResult(ok=False, error="pc_lock targets desktop devices only")
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="lock_pc", payload={}
    )
    return ToolResult(ok=True, data={"device": device.name, "command_id": cmd.id}, message="Lock queued.")
