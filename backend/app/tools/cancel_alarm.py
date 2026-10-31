"""cancel_alarm (LOW)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool


class CancelAlarmInput(BaseModel):
    alarm_id: str = Field(default="", max_length=64, description="Device alarm id; empty cancels the next alarm")
    device_name: str = Field(default="", max_length=80)


@tool(
    name="cancel_alarm",
    description="Cancel an alarm (or the next upcoming alarm) on a linked device.",
    risk=RiskTier.LOW,
    input_model=CancelAlarmInput,
    scopes=("device:alarm",),
    rate_limit_per_minute=20,
    category="alarms",
)
async def cancel_alarm(ctx: ToolContext, payload: CancelAlarmInput) -> ToolResult:
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name or None)
    if device is None:
        return ToolResult(ok=False, error="No active linked device. Pair a device first.")
    cmd = await telecom.queue_command(
        ctx.db,
        user_id=ctx.user.id,
        device=device,
        command="cancel_alarm",
        payload={"alarm_id": payload.alarm_id},
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "command_id": cmd.id},
        message=f"Alarm cancellation queued on {device.name}.",
    )
