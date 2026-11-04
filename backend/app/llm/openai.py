"""OpenAI adapter - demonstrates the swap-without-refactor promise of the interface."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.errors import classify_provider_error
from app.llm.base import FinishReason, LLMMessage, LLMResponse, ToolCall, Usage
from app.llm.claude import parse_tool_input


class OpenAIAdapter:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider_name: str = "openai",
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = settings.OPENAI_API_KEY if api_key is None else api_key
        self.model = model or settings.OPENAI_MODEL
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.name = provider_name
        self.max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _translate(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id,
                        "content": m.content,
                    }
                )
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

    def _body(self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]], *, stream: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._translate(messages),
            "max_tokens": self.max_tokens,
        }
        if tool_schemas:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t.get(
                            "input_schema", {"type": "object", "properties": {}}
                        ),
                    },
                }
                for t in tool_schemas
            ]
        if stream:
            body["stream"] = True
            # Supported by OpenAI and most compatible APIs; harmless when ignored.
            body["stream_options"] = {"include_usage": True}
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _failure(self, raw: str, *, status: int = 0) -> LLMResponse:
        classified = classify_provider_error(raw, status=status, provider=self.name)
        return LLMResponse(
            finish_reason=FinishReason.ERROR,
            error=raw[:500],
            error_code=classified.code,
            model=self.model,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        tool_schemas: list[dict[str, Any]],
        on_delta: Callable[[str], Awaitable[None]],
    ) -> LLMResponse:
        """Real SSE streaming from an OpenAI-compatible /chat/completions endpoint."""
        if not self.api_key:
            return self._failure("OpenAI API key not configured")
        body = self._body(messages, tool_schemas, stream=True)
        text_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        usage = Usage()
        finish = "stop"
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=body, headers=self._headers()
                ) as resp:
                    if resp.status_code >= 400:
                        detail = (await resp.aread())[:300].decode(errors="replace")
                        return self._failure(f"{self.name} {resp.status_code}: {detail}", status=resp.status_code)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("usage"):
                            usage = Usage(
                                int(chunk["usage"].get("prompt_tokens") or 0),
                                int(chunk["usage"].get("completion_tokens") or 0),
                            )
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0] or {}
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        piece = delta.get("content") or ""
                        if piece:
                            text_parts.append(piece)
                            await on_delta(piece)
                        for tc in delta.get("tool_calls") or []:
                            index = int(tc.get("index") or 0)
                            entry = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                entry["name"] = fn["name"]
                            if fn.get("arguments"):
                                entry["arguments"] += fn["arguments"]
        except httpx.HTTPError as exc:
            return self._failure(str(exc))
        tool_calls = [
            ToolCall(id=entry["id"] or f"call_{i}", name=entry["name"], arguments=parse_tool_input(entry["arguments"]))
            for i, entry in sorted(calls.items())
            if entry["name"]
        ]
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            finish_reason=FinishReason.TOOL_USE if tool_calls else (FinishReason.LENGTH if finish == "length" else FinishReason.STOP),
            model=self.model,
            usage=usage,
            raw_stop_reason=finish,
            streamed=True,
        )

    async def complete(
        self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
        if not self.api_key:
            return self._failure("OpenAI API key not configured")

        body = self._body(messages, tool_schemas)
        headers = self._headers()
        try:
            async with httpx.AsyncClient(
                timeout=settings.LLM_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers
                )
        except httpx.HTTPError as exc:
            return self._failure(str(exc))

        if resp.status_code >= 400:
            return self._failure(
                f"{self.name} {resp.status_code}: {resp.text[:300]}", status=resp.status_code
            )

        try:
            data = resp.json()
        except ValueError:
            return self._failure("provider returned a non-JSON success response")
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return self._failure("provider response did not contain any completion choices")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        msg = choice.get("message", {}) or {}
        if not isinstance(msg, dict):
            return LLMResponse(
                finish_reason=FinishReason.ERROR,
                error="provider completion choice did not contain a message",
                model=data.get("model", self.model),
            )
        calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=parse_tool_input(
                    (tc.get("function") or {}).get("arguments", {})
                ),
            )
            for tc in (msg.get("tool_calls") or [])
        ]
        usage = data.get("usage", {}) or {}
        finish = choice.get("finish_reason")
        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            finish_reason=FinishReason.TOOL_USE
            if calls
            else (FinishReason.LENGTH if finish == "length" else FinishReason.STOP),
            model=data.get("model", self.model),
            usage=Usage(
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            ),
            raw_stop_reason=finish or "",
        )
