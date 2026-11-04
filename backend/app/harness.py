"""Bounded harness loop: model <-> Security Gateway <-> Tool Registry.

The loop is deliberately boring and small:
  plan -> validate -> authorise -> (approve) -> execute -> feed result back

Every pause is durable (``ChatRun``) so an approval can resume the exact run
minutes later. Streaming, cancellation, model accounting, long-term memory
retrieval and context summarisation all happen here so the HTTP layer stays thin.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import audit
from app.core import runs as run_registry
from app.core.config import settings
from app.core.db import new_id
from app.core.errors import classify_provider_error
from app.llm import (
    TOOL_USE_RULES,
    FinishReason,
    LLMMessage,
    ToolCall,
    Usage,
    get_routing_adapter,
    provider_status_async,
    wrap_untrusted,
)
from app.memory import context_block, extract_explicit, retrieve, save_memory, summarise
from app.models import ChatRun, Conversation, Message, User
from app.registry import registry
from app.security import GatewayError, create_approval, execute, preflight

log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40
Emit = Callable[[dict[str, Any]], Awaitable[None]] | None


class HarnessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(slots=True)
class HarnessOutcome:
    status: str  # complete | awaiting_approval | error | stopped
    reply: str = ""
    run_id: str = ""
    approval: dict[str, Any] | None = None
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    provider: str = ""
    model: str = ""
    error: str = ""
    error_code: str = ""
    hint: str = ""
    request_id: str = ""
    message_id: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    fallback_reason: str = ""
    streamed: bool = False


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


def system_prompt(
    user: User,
    status: dict[str, Any] | None = None,
    *,
    memory: str = "",
    context_summary: str = "",
) -> str:
    status = status or {"provider": "mock", "model": "offline-rules-v1"}
    parts = [
        TOOL_USE_RULES,
        f"Today is {datetime.now(timezone.utc).date().isoformat()} (UTC).",
        f"You are speaking with {user.display_name or user.email} (role: {user.role}).",
        f"Planner: {status['provider']} / {status['model']}. Always state the actual model if asked.",
        "Web surface note: the browser has push-to-talk only - there is no OS wake word or "
        "background listening on web. Say so if asked.",
        "When a user asks you to build a website, first call web_generate, show them the "
        "preview, then propose web_deploy (high risk, needs their confirmation).",
    ]
    if memory:
        parts.append(memory)
    if context_summary:
        parts.append(
            "Older turns were summarised to fit the context window. The complete history "
            "is still stored in the database and can be searched by the user:\n"
            "<conversation_summary>\n" + context_summary + "\n</conversation_summary>"
        )
    return "\n".join(parts)


async def load_history(db: AsyncSession, conversation_id: str) -> tuple[list[LLMMessage], str]:
    """Return recent turns plus a lossless pointer summary of older turns.

    Nothing is discarded: the full ``messages`` rows stay in the database. The
    summary is persisted on the conversation so a future turn can still see it.
    """
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    recent = rows[-MAX_HISTORY_MESSAGES:]
    older = rows[:-MAX_HISTORY_MESSAGES]
    summary = summarise(
        [{"role": r.role, "content": r.content} for r in older]
    ) if older else ""
    if older:
        convo = await db.get(Conversation, conversation_id)
        if convo is not None and convo.summary != summary:
            convo.summary = summary
            await db.flush()
    out = [
        LLMMessage(role=row.role, content=row.content)
        for row in recent
        if row.role in ("user", "assistant")
    ]
    return out, summary


async def build_messages(
    db: AsyncSession,
    *,
    user: User,
    conversation_id: str,
    query: str,
) -> list[LLMMessage]:
    history, summary = await load_history(db, conversation_id)
    memories = await retrieve(db, user_id=user.id, query=query, limit=6, commit=False)
    status = await provider_status_async(db)
    return [
        LLMMessage(
            role="system",
            content=system_prompt(
                user,
                status,
                memory=context_block(memories),
                context_summary=summary,
            ),
        ),
        *history,
    ]


async def _touch_conversation(
    db: AsyncSession,
    conversation_id: str,
    *,
    provider: str = "",
    model: str = "",
    tokens: int = 0,
    message_delta: int = 0,
) -> None:
    convo = await db.get(Conversation, conversation_id)
    if convo is None:
        return
    if provider:
        convo.model = f"{provider}/{model}" if model else provider
    if tokens:
        convo.token_usage += max(0, tokens)
    if message_delta:
        convo.message_count = max(
            0,
            int(
                (
                    await db.execute(
                        select(func.count(Message.id)).where(
                            Message.conversation_id == conversation_id
                        )
                    )
                ).scalar_one()
            ),
        )


async def _seed_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    conversation_id: str,
    messages: list[LLMMessage],
    request_id: str = "",
    model_override: str | None = None,
) -> ChatRun:
    run = ChatRun(
        conversation_id=conversation_id,
        user_id=user.id,
        session_id=session_id,
        status="running",
        messages_json=json.dumps([_ser(m) for m in messages]),
        steps=0,
        request_id=request_id,
        model=model_override or "",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    run_registry.register(run.id)
    return run


async def start_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    conversation_id: str,
    user_text: str,
    ip_address: str = "",
    request_id: str = "",
    model_override: str | None = None,
    emit: Emit = None,
) -> HarnessOutcome:
    """Persist the user turn, seed a durable run and drive the loop."""
    user_msg = Message(conversation_id=conversation_id, role="user", content=user_text)
    db.add(user_msg)
    convo = await db.get(Conversation, conversation_id)
    if convo is not None:
        convo.message_count += 1
        if model_override:
            convo.model = model_override
    # Only explicit user instructions become memory; ordinary chat never does.
    explicit = extract_explicit(user_text)
    if explicit:
        category, content = explicit
        await save_memory(
            db,
            user_id=user.id,
            content=content,
            category=category,
            source="explicit",
            conversation_id=conversation_id,
            commit=False,
        )
    await db.commit()
    messages = await build_messages(db, user=user, conversation_id=conversation_id, query=user_text)
    run = await _seed_run(
        db,
        user=user,
        session_id=session_id,
        conversation_id=conversation_id,
        messages=messages,
        request_id=request_id,
        model_override=model_override,
    )
    return await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address, emit=emit)


async def regenerate_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    conversation_id: str,
    ip_address: str = "",
    request_id: str = "",
    model_override: str | None = None,
    emit: Emit = None,
) -> HarnessOutcome:
    """Replace the last assistant answer with a fresh real provider response."""
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise HarnessError("conversation_not_found", "Conversation not found")
    last = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        raise HarnessError("nothing_to_regenerate", "There is no assistant answer to regenerate")
    await db.delete(last)
    await db.commit()
    messages = await build_messages(db, user=user, conversation_id=conversation_id, query="regenerate last answer")
    run = await _seed_run(
        db,
        user=user,
        session_id=session_id,
        conversation_id=conversation_id,
        messages=messages,
        request_id=request_id,
        model_override=model_override,
    )
    return await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address, emit=emit)


async def edit_and_resend(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    message_id: str,
    new_text: str,
    ip_address: str = "",
    request_id: str = "",
    model_override: str | None = None,
    emit: Emit = None,
) -> HarnessOutcome:
    """Edit a user message, truncate every later turn, then answer the edited turn."""
    message = await db.get(Message, message_id)
    if message is None or message.role != "user":
        raise HarnessError("message_not_found", "Editable user message not found")
    convo = await db.get(Conversation, message.conversation_id)
    if convo is None or convo.user_id != user.id:
        raise HarnessError("conversation_not_found", "Conversation not found")
    later = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == convo.id,
                Message.created_at > message.created_at,
            )
        )
    ).scalars().all()
    for row in later:
        await db.delete(row)
    message.content = new_text
    message.edited_at = datetime.now(timezone.utc)
    await db.commit()
    messages = await build_messages(db, user=user, conversation_id=convo.id, query=new_text)
    run = await _seed_run(
        db,
        user=user,
        session_id=session_id,
        conversation_id=convo.id,
        messages=messages,
        request_id=request_id,
        model_override=model_override,
    )
    return await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address, emit=emit)


async def resume_run(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    run_id: str,
    approval_id: str,
    ip_address: str = "",
    emit: Emit = None,
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

    outcome = await drive(db, user=user, session_id=session_id, run=run, ip_address=ip_address, emit=emit)
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


async def _emit(event: dict[str, Any], emit: Emit) -> None:
    if emit is not None:
        await emit(event)


async def _completion(
    adapter,
    messages: list[LLMMessage],
    schemas: list[dict[str, Any]],
    emit: Emit,
    cancel_event: asyncio.Event | None,
) -> tuple[Any, str]:
    """Stream real provider deltas when a transport wants them."""
    partial: list[str] = []

    async def on_delta(piece: str) -> None:
        partial.append(piece)
        await _emit({"type": "delta", "text": piece}, emit)

    if emit is not None:
        response = await run_registry.wait_or_cancel(
            adapter.stream(messages, schemas, on_delta), cancel_event
        )
    else:
        response = await run_registry.wait_or_cancel(
            adapter.complete(messages, schemas), cancel_event
        )
    return response, "".join(partial)


async def drive(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    run: ChatRun,
    ip_address: str = "",
    emit: Emit = None,
) -> HarnessOutcome:
    adapter = get_routing_adapter(
        db,
        user_id=user.id,
        conversation_id=run.conversation_id,
        request_id=run.request_id,
        model_override=run.model or None,
    )
    schemas = registry.schemas()
    messages = [_deser(m) for m in json.loads(run.messages_json)]
    events: list[dict[str, Any]] = []
    budget = max(1, settings.HARNESS_MAX_STEPS - run.steps)
    last_provider = adapter.name
    last_model = run.model or ""
    usage_total = Usage()
    fallback_reason = ""
    streamed = False
    cancel_event = run_registry.get(run.id)
    request_id = run.request_id
    await _emit(
        {
            "type": "start",
            "run_id": run.id,
            "conversation_id": run.conversation_id,
            "request_id": request_id,
        },
        emit,
    )

    try:
        for _step in range(budget):
            run.steps += 1
            await _emit(
                {"type": "status", "stage": "planning", "step": run.steps, "provider": last_provider, "model": last_model},
                emit,
            )
            try:
                response, partial = await _completion(adapter, messages, schemas, emit, cancel_event)
            except asyncio.CancelledError:
                run.status = "stopped"
                run.stopped = True
                run.messages_json = json.dumps([_ser(m) for m in messages])
                if partial.strip():
                    stopped_msg = Message(
                        conversation_id=run.conversation_id,
                        role="assistant",
                        content=partial.strip(),
                        status="stopped",
                        provider=last_provider,
                        model=last_model,
                    )
                    db.add(stopped_msg)
                    await db.commit()
                    await db.refresh(stopped_msg)
                    await _touch_conversation(db, run.conversation_id, message_delta=1)
                await db.commit()
                await _emit({"type": "stopped", "run_id": run.id}, emit)
                return HarnessOutcome(
                    status="stopped",
                    reply=partial.strip(),
                    run_id=run.id,
                    tool_events=events,
                    steps=run.steps,
                    provider=last_provider,
                    model=last_model,
                    request_id=request_id,
                )
            last_provider = response.provider or adapter.name
            last_model = response.model or last_model
            streamed = streamed or bool(response.streamed)
            usage_total.input_tokens += response.usage.input_tokens
            usage_total.output_tokens += response.usage.output_tokens
            if response.fallback_reason:
                fallback_reason = response.fallback_reason

            if response.finish_reason is FinishReason.ERROR:
                classified = classify_provider_error(response.error or "provider returned an error")
                await _fail_run(db, run, response.error)
                await audit(
                    db,
                    action="assistant.error",
                    actor=user,
                    status="error",
                    detail={"error": response.error[:500], "code": response.error_code or classified.code},
                    ip_address=ip_address,
                )
                await _emit({"type": "error", "error": classified.message, "code": classified.code}, emit)
                return HarnessOutcome(
                    status="error",
                    run_id=run.id,
                    error=classified.message,
                    error_code=response.error_code or classified.code,
                    hint=classified.hint,
                    reply="The AI provider is unavailable right now. " + classified.hint,
                    steps=run.steps,
                    provider=last_provider,
                    model=last_model,
                    tool_events=events,
                    request_id=request_id,
                    fallback_reason=fallback_reason,
                )

            if response.text:
                messages.append(LLMMessage(role="assistant", content=response.text))

            if not response.tool_calls:
                final = response.text or "(no response)"
                assistant = Message(
                    conversation_id=run.conversation_id,
                    role="assistant",
                    content=final,
                    provider=last_provider,
                    model=last_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    status="complete",
                )
                db.add(assistant)
                run.status = "complete"
                run.provider = last_provider
                run.model = last_model
                run.messages_json = json.dumps([_ser(m) for m in messages])
                await _touch_conversation(
                    db,
                    run.conversation_id,
                    provider=last_provider,
                    model=last_model,
                    tokens=response.usage.input_tokens + response.usage.output_tokens,
                    message_delta=1,
                )
                await db.commit()
                await db.refresh(assistant)
                return HarnessOutcome(
                    status="complete",
                    reply=final,
                    run_id=run.id,
                    tool_events=events,
                    steps=run.steps,
                    provider=last_provider,
                    model=last_model,
                    request_id=request_id,
                    message_id=assistant.id,
                    usage={"input": usage_total.input_tokens, "output": usage_total.output_tokens},
                    fallback_reason=fallback_reason,
                    streamed=streamed,
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
                    event = {"tool": call.name, "risk": "unknown", "ok": False, "error": "unknown tool"}
                    events.append(event)
                    await _emit({"type": "tool", "event": event}, emit)
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
                    event = {"tool": call.name, "risk": spec.risk.value, "ok": False, "blocked": decision.reason}
                    events.append(event)
                    await _emit({"type": "tool", "event": event}, emit)
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
                    approval_payload = {
                        "id": approval.id,
                        "tool": spec.name,
                        "risk": spec.risk.value,
                        "description": spec.description,
                        "args": call.arguments,
                        "expires_at": approval.expires_at.isoformat(),
                        "action_hash": approval.action_hash,
                    }
                    _pause(run, call)
                    run.status = "awaiting_approval"
                    run.pending_approval_id = approval.id
                    run.provider = last_provider
                    run.model = last_model
                    await db.commit()
                    await _emit({"type": "approval", "approval": approval_payload}, emit)
                    return HarnessOutcome(
                        status="awaiting_approval",
                        reply=response.text,
                        run_id=run.id,
                        approval=approval_payload,
                        tool_events=events,
                        steps=run.steps,
                        provider=last_provider,
                        model=last_model,
                        request_id=request_id,
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
                    event = {"tool": spec.name, "risk": spec.risk.value, "ok": False, "blocked": exc.message}
                    events.append(event)
                    await _emit({"type": "tool", "event": event}, emit)
                    continue

                messages.append(
                    LLMMessage(
                        role="tool",
                        tool_call_id=call.id,
                        tool_name=spec.name,
                        content=wrap_untrusted(spec.name, result.to_model_text()),
                    )
                )
                event = {
                    "tool": spec.name,
                    "risk": spec.risk.value,
                    "ok": result.ok,
                    "result": result.to_payload(),
                    "dry_run": False,
                }
                events.append(event)
                await _emit({"type": "tool", "event": event}, emit)

            run.messages_json = json.dumps([_ser(m) for m in messages])
            await db.commit()

        # Budget exhausted - be honest about it rather than looping forever.
        note = (
            f"I stopped after {settings.HARNESS_MAX_STEPS} tool steps to stay within budget. "
            "Ask me to continue if you want me to keep going."
        )
        messages.append(LLMMessage(role="assistant", content=note))
        db.add(Message(conversation_id=run.conversation_id, role="assistant", content=note, status="complete"))
        run.messages_json = json.dumps([_ser(m) for m in messages])
        run.status = "budget_exhausted"
        await db.commit()
        return HarnessOutcome(
            status="complete",
            reply=note,
            run_id=run.id,
            tool_events=events,
            steps=run.steps,
            provider=last_provider,
            model=last_model,
            request_id=request_id,
        )
    finally:
        run_registry.clear(run.id)


__all__ = [
    "HarnessError",
    "HarnessOutcome",
    "build_messages",
    "drive",
    "edit_and_resend",
    "load_history",
    "new_id",
    "regenerate_run",
    "resume_run",
    "start_run",
    "system_prompt",
]
