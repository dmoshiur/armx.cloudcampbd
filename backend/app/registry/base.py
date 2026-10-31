"""Tool plugin contract.

Every capability is one small self-registering module under ``app/tools/``.
A module declares a :class:`ToolSpec` via the ``@tool`` decorator. The LLM may
only *request* a tool by name with schema-validated arguments; only the
Security Gateway decides whether it runs, and only the gateway invokes the
handler.
"""
from __future__ import annotations

import enum
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Type

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class RiskTier(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 1, "medium": 2, "high": 3}[self.value]

    @property
    def needs_approval(self) -> bool:
        return self is not RiskTier.LOW


@dataclass(slots=True)
class ToolContext:
    db: AsyncSession
    user: User
    session_id: str
    ip_address: str = ""
    dry_run: bool = False
    approval_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: str = ""

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.message:
            out["message"] = self.message
        if self.data:
            out["data"] = self.data
        if self.error:
            out["error"] = self.error
        return out

    def to_model_text(self) -> str:
        """Serialised for the LLM. Tool output is DATA, never instructions."""
        import json

        return json.dumps(self.to_payload(), default=str)[:6000]


Handler = Callable[[ToolContext, BaseModel], Awaitable[ToolResult]]
RiskResolver = Callable[["AsyncSession", "User", dict], Awaitable[RiskTier]]


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    risk: RiskTier
    input_model: Type[BaseModel]
    handler: Handler
    scopes: tuple[str, ...] = ()
    confirm: bool = False
    rate_limit_per_minute: int = 30
    dry_run_supported: bool = False
    category: str = "general"
    # Optional dynamic risk: e.g. messaging is MEDIUM for a pre-approved contact and
    # HIGH for a new one. The gateway uses this for the approval decision.
    risk_resolver: RiskResolver | None = None

    def json_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def llm_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.json_schema()}

    def definition_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk_tier": self.risk.value,
            "scopes": ",".join(self.scopes),
            "confirm_required": self.confirm or self.risk.needs_approval,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "dry_run_supported": self.dry_run_supported,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._loaded = False

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise RuntimeError(f"Duplicate tool name: {spec.name}")
        # Guard rail: MEDIUM/HIGH must never silently auto-execute.
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: (t.risk.rank, t.name))

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.llm_schema() for t in self.all()]

    def load(self) -> None:
        if self._loaded:
            return
        import app.tools as tools_pkg

        for mod in pkgutil.iter_modules(tools_pkg.__path__):
            importlib.import_module(f"app.tools.{mod.name}")
        self._loaded = True

    def validate_args(self, name: str, args: dict[str, Any]) -> BaseModel:
        spec = self._tools[name]
        try:
            return spec.input_model.model_validate(args)
        except ValidationError as exc:
            raise ToolArgumentError(name, exc) from exc


class ToolArgumentError(Exception):
    def __init__(self, tool: str, exc: ValidationError) -> None:
        self.tool = tool
        self.exc = exc
        self.detail = exc.errors(include_url=False)
        super().__init__(f"Invalid arguments for {tool}")


registry = ToolRegistry()


def tool(
    *,
    name: str,
    description: str,
    risk: RiskTier,
    input_model: Type[BaseModel],
    scopes: tuple[str, ...] = (),
    confirm: bool = False,
    rate_limit_per_minute: int = 30,
    dry_run_supported: bool = False,
    category: str = "general",
    risk_resolver: RiskResolver | None = None,
):
    """Decorator that registers a tool handler."""

    def decorator(fn: Handler) -> Handler:
        registry.register(
            ToolSpec(
                name=name,
                description=description,
                risk=risk,
                input_model=input_model,
                handler=fn,
                scopes=scopes,
                confirm=confirm,
                rate_limit_per_minute=rate_limit_per_minute,
                dry_run_supported=dry_run_supported,
                category=category,
                risk_resolver=risk_resolver,
            )
        )
        return fn

    return decorator


# Tools that remain available while the kill-switch is engaged (read-only, no integrations).
KILL_SWITCH_SAFE_TOOLS = {"health_status"}
