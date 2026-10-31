"""link_device (HIGH) - create a pending pairing for a device the caller owns.

Pairing is completed ON the device with the code shown here. The unlink password is
set by the device owner on the device (POST /api/devices/{id}/pair) and never passes
through the assistant.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field, field_validator

from app.core.security import hash_token
from app.models import DeviceStatus, LinkedDevice
from app.registry import RiskTier, ToolContext, ToolResult, tool

ALLOWED_CAPABILITIES = {"alarm", "app_launch", "state", "calls", "speak", "screen_share"}


class LinkDeviceInput(BaseModel):
    name: str = Field(min_length=2, max_length=60, description="A name you will recognise, e.g. 'Bedroom Pixel'")
    platform: str = Field(default="android", pattern="^(android|desktop|watch)$")
    capabilities: list[str] = Field(
        default_factory=lambda: ["alarm", "app_launch", "state", "calls"],
        description="Consent scopes to request: alarm, app_launch, state, calls, speak, screen_share",
    )

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, v: list[str]) -> list[str]:
        unknown = set(v) - ALLOWED_CAPABILITIES
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        return sorted(set(v))


@tool(
    name="link_device",
    description=(
        "Start pairing for one of your own devices. Returns a one-time code that must be confirmed "
        "on that device, where the owner also sets the unlink password. HIGH risk."
    ),
    risk=RiskTier.HIGH,
    input_model=LinkDeviceInput,
    scopes=("device:link", "owner_device"),
    confirm=True,
    rate_limit_per_minute=5,
    category="devices",
)
async def link_device(ctx: ToolContext, payload: LinkDeviceInput) -> ToolResult:
    if ctx.user.role not in ("vip", "admin"):
        return ToolResult(
            ok=False,
            error="Device linking requires the VIP role - ask an administrator to upgrade your account.",
        )
    if "screen_share" in payload.capabilities:
        return ToolResult(
            ok=False,
            error="Screen sharing must be granted from the device itself, not from the assistant.",
        )

    code = f"{secrets.randbelow(10**6):06d}"
    device = LinkedDevice(
        owner_id=ctx.user.id,
        name=payload.name,
        platform=payload.platform,
        status=DeviceStatus.PENDING.value,
        pairing_code_hash=hash_token(code),
        pairing_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        # Placeholder only: a real password is required before the link can activate.
        unlink_password_hash="",
        capabilities=",".join(payload.capabilities),
    )
    ctx.db.add(device)
    await ctx.db.commit()
    await ctx.db.refresh(device)

    return ToolResult(
        ok=True,
        data={
            "device_id": device.id,
            "name": device.name,
            "pairing_code": code,
            "expires_in_minutes": 10,
            "next_step": (
                "Open A.R.M.X on the device, choose 'Pair with code', enter this code and set an "
                "unlink password on the device. The link only activates after that confirmation."
            ),
        },
        message=f"Pairing started for {device.name}. Confirm the code on the device to activate it.",
    )
