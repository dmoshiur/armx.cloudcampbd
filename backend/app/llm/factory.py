"""LLM adapter construction and routing entry points."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.base import LLMAdapter
from app.llm.claude import ClaudeAdapter
from app.llm.mock import MockAdapter
from app.llm.openai import OpenAIAdapter
from app.llm.router import RoutingAdapter, provider_status_async

_adapters: dict[str, LLMAdapter] = {}


def build_adapter(provider: str | None = None) -> LLMAdapter:
    provider = (provider or settings.LLM_PROVIDER).lower()
    if provider == "groq" and settings.GROQ_API_KEY:
        return OpenAIAdapter(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            base_url=settings.GROQ_BASE_URL,
            provider_name="groq",
        )
    if provider in {"claude", "anthropic"} and settings.anthropic_key_pool:
        return ClaudeAdapter()
    if provider == "openai" and settings.OPENAI_API_KEY:
        return OpenAIAdapter()
    if provider == "mock":
        return MockAdapter()
    return MockAdapter()


def get_adapter() -> LLMAdapter:
    """Environment-only adapter retained for isolated/offline components."""
    key = settings.LLM_PROVIDER
    if key not in _adapters:
        _adapters[key] = build_adapter(key)
    return _adapters[key]


def get_routing_adapter(db: AsyncSession) -> RoutingAdapter:
    return RoutingAdapter(db)


def provider_status() -> dict[str, object]:
    """Synchronous status for contexts without a database session."""
    adapter = get_adapter()
    return {
        "provider": adapter.name,
        "model": adapter.model,
        "live": adapter.name != "mock",
        "routing": settings.LLM_ROUTING_STRATEGY,
        "enabled_models": 1 if adapter.name != "mock" else 0,
        "healthy_models": 1 if adapter.name != "mock" else 0,
        "key_pool_size": len(settings.anthropic_key_pool) if adapter.name == "claude" else 0,
        "configured_provider": settings.LLM_PROVIDER,
    }


__all__ = [
    "build_adapter",
    "get_adapter",
    "get_routing_adapter",
    "provider_status",
    "provider_status_async",
]
