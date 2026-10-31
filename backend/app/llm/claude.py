"""Anthropic Claude adapter (tool-calling via the Messages API).

Billing note: this uses the OWNER'S OWN Anthropic API key(s), billed to their own
account on standard usage-based pricing. When several keys belonging to the same
organisation are configured they are load-balanced for throughput. This platform
deliberately contains no account-rotation logic to dodge free/Pro plan limits -
that would violate Anthropic's usage policy.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.llm.base import (
    FinishReason,
    LLMError,
    LLMMessage,
    LLMResponse,
    ToolCall,
    Usage,
)

log = logging.getLogger(__name__)


class ClaudeAdapter:
    name = "claude"

    def __init__(
        self,
        *,
        api_keys: list[str] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        keys = api_keys if api_keys is not None else settings.anthropic_key_pool
        self.api_keys = [k for k in keys if k]
        self.model = model or settings.ANTHROPIC_MODEL
        self.base_url = (base_url or settings.ANTHROPIC_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self._cycle = itertools.cycle(range(max(1, len(self.api_keys))))
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_keys)

    async def _next_key(self) -> str:
        if not self.api_keys:
            raise LLMError("No Anthropic API key configured", provider=self.name)
        async with self._lock:
            return self.api_keys[next(self._cycle)]

    # -- translation ------------------------------------------------------
    @staticmethod
    def _split_system(messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content or "(no output)",
                            }
                        ],
                    }
                )
                continue
            if m.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
                continue
            out.append({"role": "user", "content": m.content})
        return "\n\n".join(system_parts), out

    # -- call -------------------------------------------------------------
    async def complete(
        self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
        system, msgs = self._split_system(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "messages": msgs,
        }
        if system:
            body["system"] = system
        if tool_schemas:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
                }
                for t in tool_schemas
            ]

        attempts = max(1, min(len(self.api_keys), 2))
        last: LLMError | None = None
        for attempt in range(attempts):
            key = await self._next_key()
            try:
                return await self._post(body, key)
            except LLMError as exc:
                last = exc
                if not exc.retryable:
                    break
                log.warning("Claude attempt %s failed (%s); rotating key", attempt + 1, exc.message)
                await asyncio.sleep(0.4 * (attempt + 1))
        assert last is not None
        return LLMResponse(
            finish_reason=FinishReason.ERROR, error=last.message, model=self.model
        )

    async def _post(self, body: dict[str, Any], key: str) -> LLMResponse:
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/v1/messages", json=body, headers=headers)

        if resp.status_code == 429 or resp.status_code >= 500:
            raise LLMError(
                f"Anthropic {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
                retryable=True,
                provider=self.name,
            )
        if resp.status_code >= 400:
            raise LLMError(
                f"Anthropic {resp.status_code}: {resp.text[:300]}",
                status=resp.status_code,
                retryable=False,
                provider=self.name,
            )

        data = resp.json()
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                raw = block.get("input", {})
                if not isinstance(raw, dict):
                    raw = {}
                calls.append(ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=raw))

        stop = data.get("stop_reason", "end_turn")
        reason = {
            "tool_use": FinishReason.TOOL_USE,
            "end_turn": FinishReason.STOP,
            "stop_sequence": FinishReason.STOP,
            "max_tokens": FinishReason.LENGTH,
            "refusal": FinishReason.REFUSAL,
        }.get(stop, FinishReason.STOP)
        if calls and reason is not FinishReason.TOOL_USE:
            reason = FinishReason.TOOL_USE

        usage_raw = data.get("usage", {}) or {}
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=calls,
            finish_reason=reason,
            model=data.get("model", self.model),
            usage=Usage(usage_raw.get("input_tokens", 0), usage_raw.get("output_tokens", 0)),
            raw_stop_reason=stop,
        )


def parse_tool_input(raw: Any) -> dict[str, Any]:
    """Some providers return tool input as a JSON string; normalise it."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
