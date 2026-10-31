"""get_state (LOW) - read allowlisted entity state."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.integrations import home_assistant
from app.registry import RiskTier, ToolContext, ToolResult, tool


class GetStateInput(BaseModel):
    entity_id: str | None = Field(
        default=None, description="Allowlisted entity id; omit to read every allowlisted entity"
    )

    @field_validator("entity_id")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in settings.allowed_entities:
            raise ValueError("entity not allowlisted")
        return v


@tool(
    name="get_state",
    description="Read the current state of allowlisted smart-home entities (one entity, or all of them).",
    risk=RiskTier.LOW,
    input_model=GetStateInput,
    scopes=("home:read",),
    rate_limit_per_minute=60,
    category="smart_home",
)
async def get_state(ctx: ToolContext, payload: GetStateInput) -> ToolResult:
    try:
        if payload.entity_id:
            data = await home_assistant.get_state(payload.entity_id)
            return ToolResult(ok=True, data=data, message=f"{payload.entity_id} is {data.get('state')}.")
        states = await home_assistant.list_allowed_states()
        if not states:
            return ToolResult(ok=False, error="No entities are allowlisted (HOME_ASSISTANT_ALLOWED_ENTITIES).")
        return ToolResult(ok=True, data={"entities": states}, message=f"{len(states)} allowlisted entities read.")
    except home_assistant.IntegrationNotConfigured as exc:
        return ToolResult(ok=False, data=exc.payload(), error=exc.hint)
    except Exception as exc:
        return ToolResult(ok=False, error=f"Home Assistant error: {exc}"[:300])
