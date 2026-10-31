"""OpenAI adapter - demonstrates the swap-without-refactor promise of the interface."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.llm.base import FinishReason, LLMMessage, LLMResponse, ToolCall, Usage
from app.llm.claude import parse_tool_input


class OpenAIAdapter:
    name = "openai"

    def __init__(
        self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None
    ) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _translate(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": __import__("json").dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    async def complete(
        self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                finish_reason=FinishReason.ERROR, error="OpenAI API key not configured", model=self.model
            )

        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._translate(messages),
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
        if tool_schemas:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
                for t in tool_schemas
            ]

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as exc:
            return LLMResponse(finish_reason=FinishReason.ERROR, error=str(exc), model=self.model)

        if resp.status_code >= 400:
            return LLMResponse(
                finish_reason=FinishReason.ERROR,
                error=f"OpenAI {resp.status_code}: {resp.text[:300]}",
                model=self.model,
            )

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=parse_tool_input((tc.get("function") or {}).get("arguments", {})),
            )
            for tc in (msg.get("tool_calls") or [])
        ]
        usage = data.get("usage", {}) or {}
        finish = choice.get("finish_reason")
        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            finish_reason=FinishReason.TOOL_USE if calls else (
                FinishReason.LENGTH if finish == "length" else FinishReason.STOP
            ),
            model=data.get("model", self.model),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            raw_stop_reason=finish or "",
        )
