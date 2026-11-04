"""Assistant: conversations, streaming harness, approvals, resumes and retries."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core import media
from app.core.config import settings
from app.core.db import as_utc, get_db
from app.core.deps import AuthContext, client_ip, get_auth_context
from app.core.errors import GATEWAY_HINTS, api_error, classify_provider_error, error_payload
from app.core.runs import stop as stop_run_event
from app.harness import (
    HarnessError,
    HarnessOutcome,
    edit_and_resend,
    regenerate_run,
    resume_run,
    start_run,
)
from app.llm import provider_status_async, wrap_untrusted
from app.llm.factory import provider_status_async as provider_status
from app.models import (
    Approval,
    ChatRun,
    Conversation,
    LLMModelConfig,
    LLMProvider,
    Message,
    MessageFeedback,
    User,
)
from app.registry import registry
from app.security import GatewayError, deny_approval, retry_approval

router = APIRouter(prefix="/assistant", tags=["assistant"])
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=160)
    attachments: list[str] = Field(default_factory=list, max_length=8)


class ApproveRequest(BaseModel):
    approval_id: str = Field(min_length=8, max_length=64)
    decision: str = Field(default="approve", pattern="^(approve|reject)$")


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None
    pinned: bool | None = None
    project_id: str | None = Field(default=None, max_length=32)


class FeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    comment: str = Field(default="", max_length=1000)


class EditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model: str | None = Field(default=None, max_length=160)


class RegenerateRequest(BaseModel):
    model: str | None = Field(default=None, max_length=160)


def _outcome(
    outcome: HarnessOutcome, conversation_id: str, *, request_id: str = ""
) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "request_id": outcome.request_id or request_id,
        "reply": outcome.reply,
        "run_id": outcome.run_id,
        "conversation_id": conversation_id,
        "approval": outcome.approval,
        "tool_events": outcome.tool_events,
        "steps": outcome.steps,
        "provider": outcome.provider,
        "model": outcome.model,
        "error": outcome.error or None,
        "error_code": outcome.error_code or None,
        "hint": outcome.hint or None,
        "message_id": outcome.message_id or None,
        "usage": outcome.usage,
        "fallback_reason": outcome.fallback_reason or None,
        "streamed": outcome.streamed,
    }


def _conversation_out(convo: Conversation) -> dict[str, Any]:
    return {
        "id": convo.id,
        "title": convo.title,
        "created_at": convo.created_at.isoformat(),
        "updated_at": convo.updated_at.isoformat(),
        "archived": convo.archived,
        "pinned": convo.pinned,
        "model": convo.model,
        "token_usage": convo.token_usage,
        "project_id": convo.project_id,
        "message_count": convo.message_count,
        "summary": convo.summary,
    }


async def _conversation(
    db: AsyncSession, user: User, conversation_id: str | None, *, title: str = "New chat"
) -> Conversation:
    if conversation_id:
        convo = await db.get(Conversation, conversation_id)
        if convo is None or convo.user_id != user.id:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo
    convo = Conversation(user_id=user.id, title=title)
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return convo


async def _validate_model(db: AsyncSession, model: str | None) -> None:
    if not model:
        return
    row = (
        await db.execute(
            select(LLMModelConfig.id)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(
                LLMModelConfig.model_id == model,
                LLMModelConfig.enabled.is_(True),
                LLMProvider.enabled.is_(True),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=400,
            detail=error_payload(
                "model_unavailable",
                f"Model '{model}' is not an enabled route. Select a model in Settings or leave the default routing active.",
                hint="Admin → Models shows every enabled model and its last health check.",
            ),
        )


async def _attachment_text(db: AsyncSession, user: User, asset_ids: list[str]) -> str:
    if not asset_ids:
        return ""
    parts: list[str] = []
    for asset_id in asset_ids[:8]:
        loaded = media.read(user.id, asset_id)
        if loaded is None:
            parts.append(f"[attachment {asset_id} not found or not owned by this account]")
            continue
        record, blob = loaded
        name = str(record.get("filename") or "attachment")[:120]
        ctype = str(record.get("content_type") or "application/octet-stream")
        if ctype in media.ALLOWED_IMAGE_TYPES:
            parts.append(
                f"[image attachment {name}, {len(blob)} bytes. Image understanding needs a "
                "vision-capable model; the file was attached but not interpreted.]"
            )
        else:
            text = media.extract_text(ctype, blob, filename=name)
            parts.append(f"[document {name}]\n{text}")
    return wrap_untrusted("user_attachments", "\n\n".join(parts)) if parts else ""


async def _prepare(
    payload: ChatRequest, request: Request, ctx: AuthContext, db: AsyncSession
) -> tuple[Conversation, str, str]:
    await _validate_model(db, payload.model)
    convo = await _conversation(db, ctx.user, payload.conversation_id)
    if convo.title == "New chat":
        convo.title = payload.message.strip()[:60] or "New chat"
        await db.commit()
    attached = await _attachment_text(db, ctx.user, payload.attachments)
    user_text = payload.message if not attached else f"{payload.message}\n\n{attached}"
    request_id = getattr(request.state, "request_id", "")
    return convo, user_text, request_id


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo, user_text, request_id = await _prepare(payload, request, ctx, db)
    try:
        outcome = await asyncio.wait_for(
            start_run(
                db,
                user=ctx.user,
                session_id=ctx.session.id,
                conversation_id=convo.id,
                user_text=user_text,
                ip_address=client_ip(request),
                request_id=request_id,
                model_override=payload.model,
            ),
            timeout=settings.ASSISTANT_REQUEST_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        await db.rollback()
        running = (
            await db.execute(
                select(ChatRun)
                .where(ChatRun.conversation_id == convo.id, ChatRun.status == "running")
                .order_by(ChatRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if running is not None:
            running.status = "error"
            await db.commit()
        log.error(
            "Assistant request %s exceeded its %.1fs deadline",
            request_id,
            settings.ASSISTANT_REQUEST_TIMEOUT_SECONDS,
        )
        raise api_error(
            504,
            "assistant_timeout",
            "The assistant pipeline did not finish in time. Check the audit log before "
            "retrying any tool command.",
            request,
            hint="Check /api/health/providers and the provider's own status page.",
            retryable=True,
        ) from exc
    except GatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=error_payload(
                exc.code,
                exc.message,
                hint=GATEWAY_HINTS.get(exc.code, ""),
                request_id=request_id,
                **exc.extra,
            ),
        ) from exc
    except HarnessError as exc:
        raise api_error(400, exc.code, exc.message, request) from exc
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await db.rollback()
        log.exception("Assistant request %s failed", request_id)
        classified = classify_provider_error(str(exc))
        raise api_error(
            503,
            classified.code,
            classified.message,
            request,
            hint=classified.hint or "Check /api/health and retry.",
            retryable=classified.retryable,
        ) from exc

    await audit(
        db,
        action="assistant.chat",
        actor=ctx.user,
        status=outcome.status,
        detail={
            "conversation_id": convo.id,
            "steps": outcome.steps,
            "provider": outcome.provider,
            "model": outcome.model,
            "fallback_reason": outcome.fallback_reason,
        },
        ip_address=client_ip(request),
    )
    return _outcome(outcome, convo.id, request_id=request_id)


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Authenticated SSE stream with real provider deltas and a stoppable run id.

    POST + fetch() is used instead of EventSource so the rotating bearer token
    stays in an Authorization header and never appears in a URL.
    """
    convo, user_text, request_id = await _prepare(payload, request, ctx, db)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            outcome = await start_run(
                db,
                user=ctx.user,
                session_id=ctx.session.id,
                conversation_id=convo.id,
                user_text=user_text,
                ip_address=client_ip(request),
                request_id=request_id,
                model_override=payload.model,
                emit=emit,
            )
            await audit(
                db,
                action="assistant.chat.stream",
                actor=ctx.user,
                status=outcome.status,
                detail={"conversation_id": convo.id, "provider": outcome.provider, "model": outcome.model},
                ip_address=client_ip(request),
            )
            await queue.put({"type": "result", "outcome": _outcome(outcome, convo.id, request_id=request_id)})
        except GatewayError as exc:
            await queue.put(
                {
                    "type": "error",
                    "error": exc.message,
                    "code": exc.code,
                    "hint": GATEWAY_HINTS.get(exc.code, ""),
                    "request_id": request_id,
                    **exc.extra,
                }
            )
        except Exception as exc:  # pragma: no cover - external fault boundary
            log.exception("Streaming assistant request %s failed", request_id)
            await queue.put(
                {
                    "type": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:400],
                    "code": "assistant_unavailable",
                    "request_id": request_id,
                    "hint": "Check /api/health and retry; the request ID matches the server log.",
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())

    async def generate() -> AsyncIterator[str]:
        yield _sse({"type": "open", "request_id": request_id, "conversation_id": convo.id})
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield _sse(event)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/runs/{run_id}/stop")
async def stop_generation(
    run_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await db.get(ChatRun, run_id)
    if run is None or run.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    cancelled = stop_run_event(run_id)
    if cancelled:
        run.stopped = True
        run.status = "stopped"
        await db.commit()
    return {
        "run_id": run_id,
        "stopped": cancelled,
        "detail": (
            "Generation was cancelled; partial text is kept."
            if cancelled
            else "This run is not in flight. Nothing was cancelled."
        ),
    }


@router.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str,
    payload: ApproveRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await db.get(ChatRun, run_id)
    if run is None or run.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    request_id = getattr(request.state, "request_id", "")

    if payload.decision == "reject":
        await deny_approval(db, approval_id=payload.approval_id, user=ctx.user)
        run.status = "rejected"
        run.pending_approval_id = None
        await db.commit()
        return {
            "status": "rejected",
            "reply": "Cancelled - nothing was executed.",
            "run_id": run.id,
            "conversation_id": run.conversation_id,
            "approval": None,
            "tool_events": [],
            "steps": 0,
            "provider": run.provider,
            "model": run.model,
            "request_id": request_id,
        }

    try:
        outcome = await resume_run(
            db,
            user=ctx.user,
            session_id=ctx.session.id,
            run_id=run_id,
            approval_id=payload.approval_id,
            ip_address=client_ip(request),
        )
    except GatewayError as exc:
        raise HTTPException(
            status_code=409 if exc.code in {"approval_expired", "approval_wrong_session"} else exc.status_code,
            detail=error_payload(
                exc.code,
                exc.message,
                hint=GATEWAY_HINTS.get(exc.code, ""),
                request_id=request_id,
                can_retry=bool(exc.extra.get("can_retry")),
                retry_url=f"/api/assistant/runs/{run_id}/retry",
            ),
        ) from exc
    except HarnessError as exc:
        raise api_error(400, exc.code, exc.message, request) from exc

    await audit(
        db,
        action="assistant.approved",
        actor=ctx.user,
        status=outcome.status,
        detail={"run_id": run_id, "approval_id": payload.approval_id},
        ip_address=client_ip(request),
    )
    return _outcome(outcome, run.conversation_id, request_id=request_id)


@router.post("/runs/{run_id}/retry")
async def retry_approval_request(
    run_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Mint a NEW approval for a paused/expired run, bound to the current session."""
    run = await db.get(ChatRun, run_id)
    if run is None or run.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"awaiting_approval", "expired"}:
        raise api_error(
            409,
            "run_not_retryable",
            f"Run is {run.status}; only awaiting or expired approvals can be retried.",
            request,
        )
    paused = json.loads(run.paused_call_json or "{}")
    spec = registry.get(paused.get("name", ""))
    if spec is None or not paused.get("name"):
        raise api_error(410, "run_corrupt", "The paused tool call is missing or no longer registered.", request)
    approval = await retry_approval(
        db,
        user=ctx.user,
        session_id=ctx.session.id,
        spec=spec,
        args=paused.get("arguments") or {},
        run=run,
    )
    await audit(
        db,
        action="approval.retried",
        actor=ctx.user,
        status="pending",
        detail={"run_id": run_id, "new_approval_id": approval.id},
        ip_address=client_ip(request),
    )
    return {
        "id": approval.id,
        "run_id": run_id,
        "tool": spec.name,
        "risk": spec.risk.value,
        "description": spec.description,
        "args": paused.get("arguments") or {},
        "expires_at": approval.expires_at.isoformat(),
        "action_hash": approval.action_hash,
        "status": "pending",
    }


@router.get("/approvals")
async def pending_approvals(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows = (
        (
            await db.execute(
                select(Approval)
                .where(Approval.user_id == ctx.user.id, Approval.status == "pending")
                .order_by(Approval.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for a in rows:
        expires = as_utc(a.expires_at)
        if expires and expires < now:
            a.status = "expired"
            continue
        run = await db.get(ChatRun, a.run_id) if a.run_id else None
        spec = registry.get(a.tool_name)
        out.append(
            {
                "id": a.id,
                "tool": a.tool_name,
                "risk": a.risk_tier,
                "description": spec.description if spec else a.tool_name,
                "args": json.loads(a.args_json or "{}"),
                "expires_at": a.expires_at.isoformat(),
                "seconds_remaining": int((expires - now).total_seconds()) if expires else 0,
                "run_id": a.run_id,
                "run_status": run.status if run else "unknown",
                "action_hash": a.action_hash,
                "status": a.status,
                "can_retry": True,
            }
        )
    if any(a.status == "expired" for a in rows):
        await db.commit()
    return out


@router.post("/conversations", status_code=201)
async def create_conversation(
    payload: ConversationPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo = await _conversation(db, ctx.user, None, title=payload.title or "New chat")
    return _conversation_out(convo)


@router.get("/conversations")
async def list_conversations(
    q: str = "",
    include_archived: bool = False,
    pinned_only: bool = False,
    limit: int = 30,
    offset: int = 0,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    conditions = [Conversation.user_id == ctx.user.id]
    if not include_archived:
        conditions.append(Conversation.archived.is_(False))
    if pinned_only:
        conditions.append(Conversation.pinned.is_(True))
    if q:
        pattern = f"%{q[:120]}%"
        # Search titles and the persisted summary, not every message by default.
        conditions.append(or_(Conversation.title.ilike(pattern), Conversation.summary.ilike(pattern)))
    total = int(
        (await db.execute(select(func.count(Conversation.id)).where(*conditions))).scalar_one()
    )
    rows = (
        (
            await db.execute(
                select(Conversation)
                .where(*conditions)
                .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_conversation_out(c) for c in rows], "total": total, "has_more": offset + len(rows) < total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    limit: int = 200,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    limit = max(1, min(limit, 500))
    total = int(
        (
            await db.execute(
                select(func.count(Message.id)).where(Message.conversation_id == convo.id)
            )
        ).scalar_one()
    )
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == convo.id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return {
        **_conversation_out(convo),
        "has_more": total > limit,
        "total_messages": total,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
                "model": m.model,
                "provider": m.provider,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "status": m.status,
                "error": m.error,
                "edited_at": m.edited_at.isoformat() if m.edited_at else None,
            }
            for m in rows
        ],
    }


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(
    conversation_id: str,
    payload: ConversationPatch,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    for field in ("title", "archived", "pinned", "project_id"):
        value = getattr(payload, field)
        if value is not None:
            setattr(convo, field, value)
    await db.commit()
    return _conversation_out(convo)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(convo)
    await db.commit()
    return None


@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    format: str = "markdown",
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    detail = await get_conversation(conversation_id, limit=500, ctx=ctx, db=db)
    if format == "json":
        body = json.dumps(detail, indent=2, default=str)
        media_type = "application/json"
        extension = "json"
    else:
        lines = [f"# {detail['title']}", ""]
        for msg in detail["messages"]:
            lines.append(f"## {msg['role']} · {msg['created_at']}")
            if msg["model"]:
                lines.append(f"_model: {msg['provider']}/{msg['model']}_")
            lines.extend(["", msg["content"], ""])
        body = "\n".join(lines)
        media_type = "text/markdown; charset=utf-8"
        extension = "md"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="armx-{conversation_id[:8]}.{extension}"'},
    )


@router.post("/conversations/{conversation_id}/regenerate")
async def regenerate(
    conversation_id: str,
    request: Request,
    payload: RegenerateRequest | None = None,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    model = payload.model if payload else None
    await _validate_model(db, model)
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    request_id = getattr(request.state, "request_id", "")
    try:
        outcome = await regenerate_run(
            db,
            user=ctx.user,
            session_id=ctx.session.id,
            conversation_id=conversation_id,
            ip_address=client_ip(request),
            request_id=request_id,
            model_override=model,
        )
    except HarnessError as exc:
        raise api_error(400, exc.code, exc.message, request) from exc
    return _outcome(outcome, conversation_id, request_id=request_id)


@router.post("/messages/{message_id}/edit-and-resend")
async def edit_message(
    message_id: str,
    payload: EditRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _validate_model(db, payload.model)
    request_id = getattr(request.state, "request_id", "")
    try:
        outcome = await edit_and_resend(
            db,
            user=ctx.user,
            session_id=ctx.session.id,
            message_id=message_id,
            new_text=payload.content,
            ip_address=client_ip(request),
            request_id=request_id,
            model_override=payload.model,
        )
    except HarnessError as exc:
        raise api_error(400, exc.code, exc.message, request) from exc
    conversation_id = await _conversation_id(db, outcome)
    return _outcome(outcome, conversation_id, request_id=request_id)


async def _conversation_id(db: AsyncSession, outcome: HarnessOutcome) -> str:
    run = await db.get(ChatRun, outcome.run_id)
    return run.conversation_id if run else ""


@router.post("/messages/{message_id}/feedback", status_code=201)
async def message_feedback(
    message_id: str,
    payload: FeedbackRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    convo = await db.get(Conversation, message.conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Message not found")
    existing = (
        await db.execute(
            select(MessageFeedback).where(
                MessageFeedback.user_id == ctx.user.id,
                MessageFeedback.message_id == message_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
    else:
        db.add(
            MessageFeedback(
                user_id=ctx.user.id,
                message_id=message_id,
                rating=payload.rating,
                comment=payload.comment,
            )
        )
    await db.commit()
    return {"message_id": message_id, "rating": payload.rating, "saved": True}


@router.get("/provider")
async def provider(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await provider_status(db)
