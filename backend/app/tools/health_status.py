"""health_status (LOW) - non-secret system and integration health."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.integrations import health as health_registry
from app.llm.factory import provider_status
from app.registry import RiskTier, ToolContext, ToolResult, tool


class HealthInput(BaseModel):
    include_integrations: bool = Field(
        default=True, description="Include per-integration configuration status (no secrets are ever returned)."
    )


@tool(
    name="health_status",
    description=(
        "Report platform health: which integrations are configured, whether the kill-switch is on, "
        "and which planner (model) is active. Never returns secrets."
    ),
    risk=RiskTier.LOW,
    input_model=HealthInput,
    scopes=("read:health",),
    rate_limit_per_minute=60,
    category="system",
)
async def health_status(ctx: ToolContext, payload: HealthInput) -> ToolResult:
    from app.security import kill_switch_engaged

    data = {
        "planner": provider_status(),
        "kill_switch": "on" if await kill_switch_engaged(ctx.db) else "off",
        "integrations": health_registry.snapshot() if payload.include_integrations else [],
        "note": "Simulated providers are labelled; nothing here is silently faked.",
    }
    return ToolResult(ok=True, data=data, message="System health collected.")
