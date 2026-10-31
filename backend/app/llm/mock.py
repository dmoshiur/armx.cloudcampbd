"""Deterministic offline planner.

Used for tests, demos and for the web app's "offline demo" badge when no
Anthropic key is configured. It follows the same contract as Claude - it only
ever *requests* tools, and the Security Gateway still authorises everything.

It is explicitly labelled as a mock in every response so nobody mistakes it for
the real model.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from app.llm.base import FinishReason, LLMMessage, LLMResponse, ToolCall, Usage

MOCK_NOTICE = "(offline planner - no ANTHROPIC_API_KEY configured; deterministic tool routing only)"


def _extract_payload(text: str) -> dict:
    """Pull the first JSON object out of a (possibly wrapped) tool result."""
    import json

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


class MockAdapter:
    name = "mock"
    model = "armx-offline-planner"

    @property
    def configured(self) -> bool:
        return True

    def _last_user(self, messages: list[LLMMessage]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content
        return ""

    @staticmethod
    def _summarise(messages: list[LLMMessage]) -> str:
        """Turn the most recent tool result into a plain-English reply."""
        for m in reversed(messages):
            if m.role != "tool":
                continue
            payload = _extract_payload(m.content)
            name = m.tool_name
            if payload.get("ok") is False:
                reason = payload.get("error") or payload.get("blocked") or "it failed"
                return f"{name} could not run: {reason}"
            data = payload.get("data", {})
            if name == "web_generate":
                lint = data.get("lint", {})
                verdict = "passed" if lint.get("ok") else "found blocking issues"
                return (
                    f"Built {data.get('name', 'your site')} from {len(data.get('files', []))} files; the design "
                    f"audit {verdict} and a preview is ready below. Say the word and I will deploy it to "
                    f"{data.get('slug', 'a new repository')} - deployment needs your confirmation first."
                )
            if name == "web_deploy":
                suffix = " (simulated pipeline)" if data.get("simulated") else ""
                return f"Deployed. Live at {data.get('url', '')}{suffix}."
            if name == "web_preview":
                return f"Preview ready for {data.get('name', 'your project')}."
            if name == "health_status":
                planner = data.get("planner", {})
                integrations = data.get("integrations", [])
                ready = [i["provider"] for i in integrations if i.get("configured")]
                return (
                    f"System is healthy. Planner: {planner.get('provider')} / {planner.get('model')}. "
                    f"Configured integrations: {', '.join(ready) if ready else 'none yet'}. "
                    f"Kill-switch: {data.get('kill_switch', 'off')}."
                )
            if name == "set_light":
                return f"{data.get('entity_id', 'Light')} is {data.get('state', 'updated')}."
            if name == "get_state":
                entities = data.get("entities") or [data]
                return "; ".join(f"{e.get('entity_id')}={e.get('state')}" for e in entities[:6])
            if name == "web_search":
                results = data.get("results", [])
                if not results:
                    return "No results came back."
                return "\n".join(f"- {r['title']} - {r['link']}" for r in results[:4])
            if name == "read_mail":
                msgs = data.get("messages", [])
                return f"{len(msgs)} messages." if msgs else "The inbox is empty."
            if name == "messaging_reply":
                return f"Message sent to {data.get('contact_name', 'the contact')}."
            return payload.get("message") or f"{name} finished."

    async def complete(
        self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
        available = {t["name"] for t in tool_schemas}
        text = self._last_user(messages)
        low = text.lower()
        pending_tool_results = sum(1 for m in messages if m.role == "tool")

        # A resumed run feeds the approved tool's result back as a human turn.
        if text.startswith("The human approved and I executed"):
            payload = _extract_payload(text)
            synthetic = LLMMessage(role="tool", content=text, tool_name="web_deploy")
            for name in ("web_deploy", "web_generate", "unlink_device", "link_device", "pc_unlock",
                         "call_answer", "call_decline", "call_place", "open_app", "image_edit",
                         "read_mail", "messaging_reply", "pc_lock"):
                if name in text[:120]:
                    synthetic.tool_name = name
                    break
            return LLMResponse(
                text=f"{MOCK_NOTICE}\n{self._summarise([synthetic])}",
                finish_reason=FinishReason.STOP,
                model=self.model,
            )

        def call(name: str, args: dict[str, Any]) -> LLMResponse:
            if name not in available:
                return LLMResponse(
                    text=f"{MOCK_NOTICE}\nThat capability ({name}) is not enabled for your account.",
                    finish_reason=FinishReason.STOP,
                    model=self.model,
                )
            return LLMResponse(
                tool_calls=[ToolCall(id=f"toolu_{uuid.uuid4().hex[:16]}", name=name, arguments=args)],
                finish_reason=FinishReason.TOOL_USE,
                model=self.model,
                usage=Usage(0, 0),
            )

        # If we already have tool results, summarise them instead of looping forever.
        if pending_tool_results:
            return LLMResponse(
                text=f"{MOCK_NOTICE}\n{self._summarise(messages)}",
                finish_reason=FinishReason.STOP,
                model=self.model,
            )

        m = re.search(r"light\.([a-z0-9_]+)", low)
        if ("light" in low or "lamp" in low) and any(
            w in low for w in ("on", "off", "turn", "switch", "bright")
        ):
            entity = f"light.{m.group(1)}" if m else "light.living_room"
            if "off" in low:
                return call("set_light", {"entity_id": entity, "state": "off"})
            if "dim" in low or "bright" in low:
                pct = re.search(r"(\d{1,3})\s*%", text)
                return call(
                    "set_light",
                    {"entity_id": entity, "state": "on", "brightness_pct": int(pct.group(1)) if pct else 40},
                )
            return call("set_light", {"entity_id": entity, "state": "on"})

        if "health" in low or "status" in low or "system" in low:
            return call("health_status", {})
        if "search" in low or low.startswith("look up") or "latest" in low:
            query = re.sub(r"^(please\s+)?(search|look up)\s+(for\s+)?", "", text, flags=re.I)
            return call("web_search", {"query": query[:200] or text[:200], "max_results": 3})
        if "deploy" in low or "go live" in low or "publish" in low:
            return call("web_deploy", {})
        if "build" in low or "website" in low or "web app" in low or "landing page" in low:
            words = re.sub(r"[^a-z0-9 ]+", " ", low).split()
            for lead in ("build", "create", "make", "generate", "design"):
                if words and words[0] == lead:
                    words = words[1:]
            stop = {"me", "a", "an", "the", "website", "site", "web", "app", "landing", "page", "for"}
            while words and words[0] in stop:
                words = words[1:]
            words = [w for w in words if w not in {"in", "at", "of", "for", "to", "with", "and", "on"}]
            name = " ".join(words[:4]) or "site"
            return call("web_generate", {"prompt": text[:1200], "name": name[:40]})
        if "alarm" in low:
            tm = re.search(r"(\d{1,2})[:.](\d{2})", text)
            at = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "07:00"
            return call("set_alarm", {"time": at, "label": "Alarm", "device_name": ""})
        if "state" in low or "temperature" in low:
            return call("get_state", {"entity_id": None})

        return LLMResponse(
            text=(
                f"{MOCK_NOTICE}\nI can control lights, check health, search the web, set alarms, "
                f"generate and deploy sites, read mail and message approved contacts. "
                f"Configure ANTHROPIC_API_KEY to talk to Claude for open-ended conversation.\n\n"
                f"You said: {text[:300]}"
            ),
            finish_reason=FinishReason.STOP,
            model=self.model,
        )
