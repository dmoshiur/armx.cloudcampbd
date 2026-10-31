"""set_light (LOW) - Home Assistant light/switch control, allowlisted entities only."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.integrations import home_assistant
from app.registry import RiskTier, ToolContext, ToolResult, tool


class SetLightInput(BaseModel):
    entity_id: str = Field(description="Allowlisted Home Assistant entity, e.g. light.living_room")
    state: Literal["on", "off"] = Field(description="Desired state")
    brightness_pct: int | None = Field(
        default=None, ge=1, le=100, description="Optional brightness percentage (lights only)"
    )

    @field_validator("entity_id")
    @classmethod
    def _check_entity(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in settings.allowed_entities:
            allowed = ", ".join(sorted(settings.allowed_entities)) or "(none configured)"
            raise ValueError(f"entity not allowlisted; allowed: {allowed}")
        return v


@tool(
    name="set_light",
    description=(
        "Turn an allowlisted smart-home light or switch on or off, optionally setting brightness. "
        "Only entities in the owner's allowlist can be reached."
    ),
    risk=RiskTier.LOW,
    input_model=SetLightInput,
    scopes=("home:write",),
    rate_limit_per_minute=30,
    dry_run_supported=True,
    category="smart_home",
)
async def set_light(ctx: ToolContext, payload: SetLightInput) -> ToolResult:
    if ctx.dry_run:
        return ToolResult(
            ok=True,
            data={"entity_id": payload.entity_id, "state": payload.state, "dry_run": True},
            message=f"Dry run: would set {payload.entity_id} to {payload.state}.",
        )
    try:
        if payload.state == "on":
            result = await home_assistant.turn_on(payload.entity_id, payload.brightness_pct)
        else:
            result = await home_assistant.turn_off(payload.entity_id)
    except home_assistant.IntegrationNotConfigured as exc:
        return ToolResult(ok=False, data=exc.payload(), error=exc.hint)
    except PermissionError as exc:
        return ToolResult(ok=False, error=str(exc))
    except Exception as exc:  # network/HA error
        return ToolResult(ok=False, error=f"Home Assistant error: {exc}"[:300])
    return ToolResult(ok=True, data=result, message=f"{payload.entity_id} is now {payload.state}.")
