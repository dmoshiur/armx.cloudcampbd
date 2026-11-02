from __future__ import annotations

import asyncio

from app.core.config import settings
from app.llm.base import LLMMessage
from app.llm.openai import OpenAIAdapter


async def test_chat_deadline_returns_visible_diagnostic(client, auth_headers, monkeypatch):
    async def never_finishes(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(settings, "ASSISTANT_REQUEST_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("app.api.assistant.start_run", never_finishes)

    response = await client.post(
        "/api/assistant/chat",
        headers=auth_headers,
        json={"message": "hello"},
    )
    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["code"] == "assistant_timeout"
    assert detail["request_id"] == response.headers["x-request-id"]
    assert "did not finish" in detail["detail"]
    assert "audit log" in detail["detail"]


async def test_openai_adapter_rejects_malformed_success_payload(monkeypatch):
    class Response:
        status_code = 200
        text = "not json"

        def json(self):
            raise ValueError("bad json")

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("app.llm.openai.httpx.AsyncClient", Client)
    adapter = OpenAIAdapter(
        api_key="test-key",
        model="test-model",
        base_url="https://llm.example.com/v1",
        provider_name="test",
    )
    response = await adapter.complete([LLMMessage(role="user", content="hello")], [])
    assert not response.ok
    assert response.error == "provider returned a non-JSON success response"
