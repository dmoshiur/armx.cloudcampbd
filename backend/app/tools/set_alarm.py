"""set_alarm (LOW) - alarm on a linked device owned by the caller."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class SetAlarmInput(BaseModel):
    time: str = Field(description="24-hour HH:MM, e.g. 07:30")
    label: str = Field(default="Alarm", max_length=60)
    device_name: str = Field(default="", max_length=80, description="Target linked device (optional)")

    @field_validator("time")
    @classmethod
    def _check_time(cls, v: str) -> str:
        v = v.strip()
        if not TIME_RE.match(v):
            raise ValueError("time must be HH:MM in 24-hour form")
        return f"{int(v.split(':')[0]):02d}:{v.split(':')[1]}"


@tool(
    name="set_alarm",
    description="Set an alarm on one of the owner's linked devices. The device shows it immediately.",
    risk=RiskTier.LOW,
    input_model=SetAlarmInput,
    scopes=("device:alarm",),
    rate_limit_per_minute=20,
    category="alarms",
)
async def set_alarm(ctx: ToolContext, payload: SetAlarmInput) -> ToolResult:
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name or None)
    if device is None:
        return ToolResult(ok=False, error="No active linked device. Pair a device first.")

    hour, minute = (int(x) for x in payload.time.split(":"))
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    cmd = await telecom.queue_command(
        ctx.db,
        user_id=ctx.user.id,
        device=device,
        command="set_alarm",
        payload={"time": payload.time, "label": payload.label, "scheduled_for": target.isoformat()},
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "command_id": cmd.id, "time": payload.time, "next_ring": target.isoformat()},
        message=f"Alarm set for {payload.time} on {device.name}.",
    )
