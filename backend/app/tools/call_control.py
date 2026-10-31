"""Call control (HIGH) - owner's own device only, always visible on that device.

There is no call recording, no silent interception and no call/SMS forwarding
anywhere in this codebase. Every action is queued as a command the paired device
shows and executes locally through the Android Telecom APIs.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool

E164 = re.compile(r"^\+?[1-9]\d{6,14}$")
E164_STRICT = re.compile(r"^\+[1-9]\d{6,14}$")


class CallInput(BaseModel):
    device_name: str = Field(default="", max_length=80, description="Target linked device")

    @field_validator("device_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class PlaceCallInput(CallInput):
    contact_number: str = Field(description="E.164 number, e.g. +8801700000000")

    @field_validator("contact_number")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "").replace("-", "")
        if not E164_STRICT.match(v):
            raise ValueError("number must be in strict E.164 form (+countrycode...)")
        return v


async def _device(ctx: ToolContext, name: str):
    device = await telecom.pick_device(ctx.db, ctx.user.id, name or None)
    if device is None:
        return None, ToolResult(ok=False, error="No active linked device. Pair one first.")
    if "calls" not in (device.capabilities or ""):
        return None, ToolResult(ok=False, error="This device link does not grant call control.")
    return device, None


@tool(
    name="call_answer",
    description="Answer an incoming call on the owner's own linked device. Visible on the device; HIGH risk.",
    risk=RiskTier.HIGH,
    input_model=CallInput,
    scopes=("device:calls", "owner_device"),
    confirm=True,
    rate_limit_per_minute=10,
    category="calls",
)
async def call_answer(ctx: ToolContext, payload: CallInput) -> ToolResult:
    device, err = await _device(ctx, payload.device_name)
    if err:
        return err
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="answer_call", payload={}
    )
    return ToolResult(ok=True, data={"device": device.name, "command_id": cmd.id}, message="Answer queued.")


@tool(
    name="call_decline",
    description="Decline an incoming call on the owner's own linked device. Visible on the device; HIGH risk.",
    risk=RiskTier.HIGH,
    input_model=CallInput,
    scopes=("device:calls", "owner_device"),
    confirm=True,
    rate_limit_per_minute=10,
    category="calls",
)
async def call_decline(ctx: ToolContext, payload: CallInput) -> ToolResult:
    device, err = await _device(ctx, payload.device_name)
    if err:
        return err
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="decline_call", payload={}
    )
    return ToolResult(ok=True, data={"device": device.name, "command_id": cmd.id}, message="Decline queued.")


@tool(
    name="call_place",
    description=(
        "Place an outbound call from the owner's own linked device to a strict E.164 number. "
        "The device shows the call immediately; HIGH risk."
    ),
    risk=RiskTier.HIGH,
    input_model=PlaceCallInput,
    scopes=("device:calls", "owner_device"),
    confirm=True,
    rate_limit_per_minute=5,
    category="calls",
)
async def call_place(ctx: ToolContext, payload: PlaceCallInput) -> ToolResult:
    device, err = await _device(ctx, payload.device_name)
    if err:
        return err
    cmd = await telecom.queue_command(
        ctx.db,
        user_id=ctx.user.id,
        device=device,
        command="place_call",
        payload={"number": payload.contact_number},
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "command_id": cmd.id, "number": payload.contact_number},
        message=f"Call to {payload.contact_number} queued on {device.name}.",
    )
