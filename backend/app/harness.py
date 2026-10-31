"""Bounded harness loop: Claude <-> Security Gateway <-> Tool Registry.

The loop is deliberately boring and small:
  plan -> validate -> authorise -> (approve) -> execute -> feed result back

Every pause is durable (``ChatRun``) so an approval can resume the exact run
minutes later, and every step is audited.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import audit
from app.core.config import settings
from app.core.db import new_id
from app.llm import (
    TOOL_USE_RULES,
    FinishReason,
    LLMMessage,
    ToolCall,
    get_adapter,
    wrap_untrusted,
)
from app.models import ChatRun, Message, User
from app.registry import registry
from app.security import GatewayError, create_approval, execute, preflight

log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40


class HarnessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(slots=True)
class HarnessOutcome:
    status: str  # complete | awaiting_approval | error
    reply: str = ""
    run_id: str = ""
    approval: dict[str, Any] | None = None
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    provider: str = ""
    error: str = ""


def _ser(msg: LLMMessage) -> dict[str, Any]:
    return {
        "role": msg.role,
        "content": msg.content,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in msg.tool_calls
        ],
        "tool_call_id": msg.tool_call_id,
        "tool_name": msg.tool_name,
    }


def _deser(raw: dict[str, Any]) -> LLMMessage:
    return LLMMessage(
        role=raw.get("role", "user"),
        content=raw.get("content", ""),
        tool_calls=[
            ToolCall(id=c.get("id", ""), name=c.get("name", ""), arguments=c.get("arguments") or {})
            for c in raw.get("tool_calls", [])
        ],
        tool_call_id=raw.get("tool_call_id", ""),
        tool_name=raw.get("tool_name", ""),
    )


def system_prompt(user: User) -> str:
    from app.llm.factory import provider_status

    status = provider_status()
    return (
        f"{TOOL_USE_RULES}\n"
        f"Today is {datetime.now(timezone.utc).date().isoformat()} (UTC).\n"
        f"You are speaking with {user.display_name or user.email} (role: {user.role}).\n"
        f"Planner: {status['provider']} / {status['model']}.\n"
        "Web surface note: the browser has push-to-talk only - there is no OS wake word or "
        "background listening on web. Say so if asked.\n"
        "When a user asks you to build a website, first call web_generate, show them the "
        "preview, then propose web_deploy (high risk, needs their confirmation).\n"
    )


async def load_history(db: AsyncSession, conversation_id: str) -> list[LLMMessage]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    out: list[LLMMessage] = []
    for row in rows[-MAX_HISTORY_MESSAGES:]:
        if row.role in ("user", "assistant"):
            out.append(LLMMessage(role=row.role, content=row.content))
    return out


async def start_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    conversation_id: str,
    user_text: str,
    ip_address: str = "",
) -> HarnessOutcome:
    """Persist the user turn, seed a durable run and drive the loop."""
    user_msg = Message(conversation_id=conversation_id, role="user", content=user_text)
    db.add(user_msg)
    await db.commit()

    history = await load_history(db, conversation_id)
    messages = [LLMMessage(role="system", content=system_prompt(user)), *history]

    run = ChatRun(
        conversation_id=conversation_id,
        user_id=user.id,
        session_id=session_id,
        status="running",
        messages_json=json.dumps([_ser(m) for m in messages]),
        steps=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    return await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address)


async def resume_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    run_id: str,
    approval_id: str,
    ip_address: str = "",
) -> HarnessOutcome:
    run = await db.get(ChatRun, run_id)
    if run is None or run.user_id != user.id:
        raise HarnessError("run_not_found", "Run not found")
    if run.status != "awaiting_approval":
        raise HarnessError("run_not_waiting", f"Run is {run.status}, not awaiting approval")

    paused = json.loads(run.paused_call_json or "{}")
    if not paused.get("name"):
        raise HarnessError("run_corrupt", "Run has no paused tool call")

    spec = registry.get(paused["name"])
    if spec is None:
        raise HarnessError("unknown_tool", "Paused tool no longer exists")

    args = paused.get("arguments") or {}

    # `execute` burns the approval itself (single-use), so do not consume it twice.
    try:
        result = await execute(
            db,
            user=user,
            session_id=session_id,
            tool_name=spec.name,
            args=args,
            approval_id=approval_id,
            ip_address=ip_address,
        )
    except GatewayError as exc:
        await _fail_run(db, run, exc.message)
        raise HarnessError(exc.code, exc.message) from exc

    messages = [_deser(m) for m in json.loads(run.messages_json)]
    messages.append(
        LLMMessage(
            role="user",
            content=(
                f"The human approved and I executed {spec.name}. Result:\n"
                f"{wrap_untrusted(spec.name, result.to_model_text())}"
            ),
        )
    )
    run.messages_json = json.dumps([_ser(m) for m in messages])
    run.paused_call_json = "{}"
    run.status = "running"
    run.pending_approval_id = None
    await db.commit()

    outcome = await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address)
    outcome.tool_events.insert(
        0,
        {
            "tool": spec.name,
            "risk": spec.risk.value,
            "ok": result.ok,
            "result": result.to_payload(),
            "approved": True,
        },
    )
    return outcome


def _pause(run: ChatRun, call: ToolCall) -> None:
    run.paused_call_json = json.dumps({"id": call.id, "name": call.name, "arguments": call.arguments})


async def _fail_run(db: AsyncSession, run: ChatRun, message: str) -> None:
    run.status = "failed"
    await db.commit()
    log.warning("Run %s failed: %s", run.id, message)


async def drive(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    run: ChatRun,
    ip_address: str = "",
) -> HarnessOutcome:
    adapter = get_adapter()
    schemas = registry.schemas()
    messages = [_deser(m) for m in json.loads(run.messages_json)]
    events: list[dict[str, Any]] = []
    budget = max(1, settings.HARNESS_MAX_STEPS - run.steps)

    for _step in range(budget):
        run.steps += 1
        response = await adapter.complete(messages, schemas)

        if response.finish_reason is FinishReason.ERROR:
            await _fail_run(db, run, response.error)
            await audit(
                db,
                action="assistant.error",
                actor=user,
                status="error",
                detail={"error": response.error[:500]},
                ip_address=ip_address,
            )
            return HarnessOutcome(
                status="error",
                run_id=run.id,
                error=response.error,
                reply=(
                    "The AI provider is unavailable right now. "
                    + ("" if adapter.name != "mock" else "This instance is using the offline planner.")
                ),
                steps=run.steps,
                provider=adapter.name,
                tool_events=events,
            )

        if response.text:
            messages.append(LLMMessage(role="assistant", content=response.text))

        if not response.tool_calls:
            final = response.text or "(no response)"
            db.add(Message(conversation_id=run.conversation_id, role="assistant", content=final))
            run.status = "complete"
            run.messages_json = json.dumps([_ser(m) for m in messages])
            await db.commit()
            return HarnessOutcome(
                status="complete",
                reply=final,
                run_id=run.id,
                tool_events=events,
                steps=run.steps,
                provider=adapter.name,
            )

        # Record the assistant's tool-use turn exactly once.
        messages.append(
            LLMMessage(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )

        for call in response.tool_calls:
            spec = registry.get(call.name)
            if spec is None:
                messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content=json.dumps({"ok": False, "error": f"Unknown tool '{call.name}'"}),
                    )
                )
                events.append({"tool": call.name, "risk": "unknown", "ok": False, "error": "unknown tool"})
                continue

            decision = await preflight(
                db, spec=spec, user=user, session_id=session_id, args=call.arguments
            )
            if not decision.allowed:
                messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content=json.dumps({"ok": False, "blocked": decision.reason}),
                    )
                )
                events.append(
                    {"tool": call.name, "risk": spec.risk.value, "ok": False, "blocked": decision.reason}
                )
                continue

            if decision.needs_approval:
                approval = await create_approval(
                    db,
                    user=user,
                    session_id=session_id,
                    spec=spec,
                    args=call.arguments,
                    run_id=run.id,
                )
                # Every tool_use needs a tool_result before the next model call.
                for remaining in response.tool_calls:
                    messages.append(
                        LLMMessage(
                            role="tool",
                            tool_call_id=remaining.id,
                            tool_name=remaining.name,
                            content=json.dumps(
                                {
                                    "ok": False,
                                    "status": "awaiting_human_approval",
                                    "note": "Not executed. The human must approve this exact action.",
                                }
                            ),
                        )
                    )
                _pause(run, call)
                run.status = "awaiting_approval"
                run.pending_approval_id = approval.id
                await db.commit()
                return HarnessOutcome(
                    status="awaiting_approval",
                    reply=response.text,
                    run_id=run.id,
                    approval={
                        "id": approval.id,
                        "tool": spec.name,
                        "risk": spec.risk.value,
                        "description": spec.description,
                        "args": call.arguments,
                        "expires_at": approval.expires_at.isoformat(),
                        "action_hash": approval.action_hash,
                    },
                    tool_events=events,
                    steps=run.steps,
                    provider=adapter.name,
                )

            try:
                result = await execute(
                    db,
                    user=user,
                    session_id=session_id,
                    tool_name=spec.name,
                    args=call.arguments,
                    ip_address=ip_address,
                )
            except GatewayError as exc:
                messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content=json.dumps({"ok": False, "blocked": exc.message}),
                    )
                )
                events.append({"tool": spec.name, "risk": spec.risk.value, "ok": False, "blocked": exc.message})
                continue

            messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=call.id,
                    tool_name=spec.name,
                    content=wrap_untrusted(spec.name, result.to_model_text()),
                )
            )
            events.append(
                {
                    "tool": spec.name,
                    "risk": spec.risk.value,
                    "ok": result.ok,
                    "result": result.to_payload(),
                    "dry_run": False,
                }
            )

        run.messages_json = json.dumps([_ser(m) for m in messages])
        await db.commit()

    # Budget exhausted - be honest about it rather than looping forever.
    note = (
        f"I stopped after {settings.HARNESS_MAX_STEPS} tool steps to stay within budget. "
        "Ask me to continue if you want me to keep going."
    )
    messages.append(LLMMessage(role="assistant", content=note))
    db.add(Message(conversation_id=run.conversation_id, role="assistant", content=note))
    run.messages_json = json.dumps([_ser(m) for m in messages])
    run.status = "budget_exhausted"
    await db.commit()
    return HarnessOutcome(
        status="complete",
        reply=note,
        run_id=run.id,
        tool_events=events,
        steps=run.steps,
        provider=adapter.name,
    )


__all__ = [
    "HarnessError",
    "HarnessOutcome",
    "drive",
    "load_history",
    "new_id",
    "resume_run",
    "start_run",
    "system_prompt",
]
