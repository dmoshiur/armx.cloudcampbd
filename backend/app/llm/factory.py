"""Adapter selection. One config value swaps providers."""
from __future__ import annotations

from app.core.config import settings
from app.llm.base import LLMAdapter
from app.llm.claude import ClaudeAdapter
from app.llm.mock import MockAdapter
from app.llm.openai import OpenAIAdapter

_adapters: dict[str, LLMAdapter] = {}


def build_adapter(provider: str | None = None) -> LLMAdapter:
    provider = (provider or settings.LLM_PROVIDER).lower()
    if provider == "claude" and settings.anthropic_key_pool:
        return ClaudeAdapter()
    if provider == "openai" and settings.OPENAI_API_KEY:
        return OpenAIAdapter()
    if provider == "mock":
        return MockAdapter()
    # Configured provider unusable -> fall back to the offline planner, loudly.
    return MockAdapter()


def get_adapter() -> LLMAdapter:
    key = settings.LLM_PROVIDER
    if key not in _adapters:
        _adapters[key] = build_adapter(key)
    return _adapters[key]


def provider_status() -> dict[str, object]:
    adapter = get_adapter()
    return {
        "provider": adapter.name,
        "model": adapter.model,
        "live": adapter.name != "mock",
        "key_pool_size": len(settings.anthropic_key_pool) if adapter.name == "claude" else 0,
        "configured_provider": settings.LLM_PROVIDER,
    }
