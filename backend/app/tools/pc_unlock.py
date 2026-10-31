"""pc_unlock (HIGH) - device-held signed proof, never voice or face alone.

The desktop client holds a private key and periodically mints a short-lived signed
proof after a local biometric + PIN check. The assistant can only spend that proof;
it can never mint it, and a spoken "unlock my PC" is not sufficient by design.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.integrations import telecom
from app.registry import RiskTier, ToolContext, ToolResult, tool
from app.security.tickets import DEVICE_PROOF_TICKET, spend_ticket


class PcUnlockInput(BaseModel):
    device_name: str = Field(min_length=1, max_length=80)
    proof_token: str = Field(
        min_length=8,
        max_length=200,
        description="Proof minted by the desktop client after its local biometric/PIN check",
    )


@tool(
    name="pc_unlock",
    description=(
        "Unlock the owner's desktop using a proof token minted on the device after a local "
        "biometric/PIN check. Voice or face alone is never sufficient. HIGH risk."
    ),
    risk=RiskTier.HIGH,
    input_model=PcUnlockInput,
    scopes=("device:desktop", "owner_device"),
    confirm=True,
    rate_limit_per_minute=3,
    category="device",
)
async def pc_unlock(ctx: ToolContext, payload: PcUnlockInput) -> ToolResult:
    device = await telecom.pick_device(ctx.db, ctx.user.id, payload.device_name)
    if device is None or device.platform != "desktop":
        return ToolResult(ok=False, error="No active linked desktop device with that name")

    valid = await spend_ticket(
        ctx.db, kind=DEVICE_PROOF_TICKET, user_id=ctx.user.id, token=payload.proof_token, subject=device.id
    )
    if not valid:
        return ToolResult(
            ok=False,
            error=(
                "No valid device proof. Unlocking requires the device to confirm a local "
                "biometric/PIN check - a spoken request alone is never enough."
            ),
        )
    cmd = await telecom.queue_command(
        ctx.db, user_id=ctx.user.id, device=device, command="unlock_pc", payload={}
    )
    return ToolResult(
        ok=True,
        data={"device": device.name, "command_id": cmd.id},
        message="Unlock queued after device-verified proof.",
    )
