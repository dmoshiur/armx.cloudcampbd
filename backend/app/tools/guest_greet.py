"""guest_greet (LOW) - spoken welcome with NO visitor identification."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool

GENERIC_GREETINGS = {
    "arrival": "Welcome. The owner will be with you shortly.",
    "evening": "Good evening, and welcome.",
    "delivery": "Hello - please leave the parcel at the door. Thank you.",
}

BLOCKED_PATTERNS = ("you are", "your name is", "identified as", "we recognise", "we recognize", "this is ")


class GuestGreetInput(BaseModel):
    greeting: str = Field(default="arrival", max_length=80, description="arrival | evening | delivery | custom text")
    device_name: str = Field(default="", max_length=80, description="Target linked device (optional)")


@tool(
    name="guest_greet",
    description=(
        "Speak a short, generic welcome through a linked speaker/device. Never identifies, "
        "names or profiles an unknown visitor; personalisation attempts are refused."
    ),
    risk=RiskTier.LOW,
    input_model=GuestGreetInput,
    scopes=("device:speak",),
    rate_limit_per_minute=10,
    category="guest",
)
async def guest_greet(ctx: ToolContext, payload: GuestGreetInput) -> ToolResult:
    text = GENERIC_GREETINGS.get(payload.greeting.lower().strip(), payload.greeting.strip())
    if any(p in text.lower() for p in BLOCKED_PATTERNS):
        return ToolResult(
            ok=False,
            error="Guest greetings must stay generic: this platform never identifies unknown visitors.",
        )
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name or None)
    if device is None:
        return ToolResult(ok=False, error="No active linked device. Pair a device first.")
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="speak", payload={"text": text[:200]}
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "command_id": cmd.id, "spoken": text},
        message=f"Welcome message queued on {device.name} (visible on the device).",
    )
