"""open_app (MEDIUM) - launch an installed app on the owner's own device."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool

PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

FRIENDLY_ALIASES = {
    "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome",
    "spotify": "com.spotify.music",
    "telegram": "org.telegram.messenger",
}


class OpenAppInput(BaseModel):
    app: str = Field(description="Package name (com.example.app) or a known alias such as whatsapp")
    device_name: str = Field(default="", max_length=80)

    @field_validator("app")
    @classmethod
    def _check(cls, v: str) -> str:
        v = v.strip().lower()
        v = FRIENDLY_ALIASES.get(v, v)
        if not PACKAGE_RE.match(v):
            raise ValueError("app must be a package name like com.example.app")
        if v not in telecom.DEFAULT_ALLOWED_PACKAGES:
            raise ValueError(
                "package not in the permitted list: " + ", ".join(telecom.DEFAULT_ALLOWED_PACKAGES)
            )
        return v


@tool(
    name="open_app",
    description=(
        "Launch an app on the owner's own linked device from a fixed permitted package list. "
        "The device shows a visible launch notice."
    ),
    risk=RiskTier.MEDIUM,
    input_model=OpenAppInput,
    scopes=("device:app_launch", "owner_device"),
    confirm=True,
    rate_limit_per_minute=10,
    category="device",
)
async def open_app(ctx: ToolContext, payload: OpenAppInput) -> ToolResult:
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name or None)
    if device is None:
        return ToolResult(ok=False, error="No active linked device. Pair a device first.")
    if ctx.dry_run:
        return ToolResult(ok=True, data={"app": payload.app, "device": device.name, "dry_run": True})
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="open_app", payload={"package": payload.app}
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "package": payload.app, "command_id": cmd.id},
        message=f"{payload.app} launch queued on {device.name}.",
    )
