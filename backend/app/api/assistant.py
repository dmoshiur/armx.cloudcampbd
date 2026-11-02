"""Assistant: conversations, the harness, approvals and resumes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth_context, client_ip
from app.harness import HarnessError, HarnessOutcome, resume_run, start_run
from app.llm.factory import provider_status_async
from app.models import Approval, ChatRun, Conversation, Message, User
from app.security import GatewayError, deny_approval

router = APIRouter(prefix="/assistant", tags=["assistant"])
log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=32)


class ApproveRequest(BaseModel):
    approval_id: str = Field(min_length=8, max_length=64)
    decision: str = Field(default="approve", pattern="^(approve|reject)$")


def _outcome(
    outcome: HarnessOutcome, conversation_id: str, *, request_id: str = ""
) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "request_id": request_id,
        "reply": outcome.reply,
        "run_id": outcome.run_id,
        "conversation_id": conversation_id,
        "approval": outcome.approval,
        "tool_events": outcome.tool_events,
        "steps": outcome.steps,
        "provider": outcome.provider,
        "error": outcome.error or None,
    }


async def _conversation(
    db: AsyncSession, user: User, conversation_id: str | None
) -> Conversation:
    if conversation_id:
        convo = await db.get(Conversation, conversation_id)
        if convo is None or convo.user_id != user.id:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo
    convo = Conversation(user_id=user.id, title="New chat")
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return convo


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo = await _conversation(db, ctx.user, payload.conversation_id)
    if convo.title == "New chat":
        convo.title = payload.message.strip()[:60]
        await db.commit()

    request_id = getattr(request.state, "request_id", "")
    try:
        outcome = await asyncio.wait_for(
            start_run(
                db,
                user=ctx.user,
                session_id=ctx.session.id,
                conversation_id=convo.id,
                user_text=payload.message,
                ip_address=client_ip(request),
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
        raise HTTPException(
            status_code=504,
            detail={
                "code": "assistant_timeout",
                "detail": (
                    "The assistant pipeline did not finish in time. Check the audit log before "
                    "retrying any tool command."
                ),
                "request_id": request_id,
            },
        ) from exc
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except HarnessError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "detail": exc.message}
        ) from exc
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await db.rollback()
        log.exception("Assistant request %s failed", request_id)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "assistant_unavailable",
                "detail": "The assistant could not complete this request.",
                "request_id": request_id,
            },
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
        },
        ip_address=client_ip(request),
    )
    return _outcome(outcome, convo.id, request_id=request_id)


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

    if payload.decision == "reject":
        await deny_approval(db, approval_id=payload.approval_id, user=ctx.user)
        run.status = "rejected"
        await db.commit()
        return {
            "status": "rejected",
            "reply": "Cancelled - nothing was executed.",
            "run_id": run.id,
            "conversation_id": run.conversation_id,
            "approval": None,
            "tool_events": [],
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
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except HarnessError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "detail": exc.message}
        ) from exc

    await audit(
        db,
        action="assistant.approved",
        actor=ctx.user,
        status=outcome.status,
        detail={"run_id": run_id, "approval_id": payload.approval_id},
        ip_address=client_ip(request),
    )
    return _outcome(
        outcome,
        run.conversation_id,
        request_id=getattr(request.state, "request_id", ""),
    )


@router.get("/approvals")
async def pending_approvals(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
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
    return [
        {
            "id": a.id,
            "tool": a.tool_name,
            "risk": a.risk_tier,
            "args": a.args_json,
            "expires_at": a.expires_at.isoformat(),
            "run_id": a.run_id,
            "action_hash": a.action_hash,
        }
        for a in rows
    ]


@router.get("/conversations")
async def list_conversations(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(Conversation)
                .where(Conversation.user_id == ctx.user.id)
                .order_by(Conversation.updated_at.desc())
                .limit(60)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "updated_at": c.updated_at.isoformat(),
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convo = await db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == convo.id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": convo.id,
        "title": convo.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
    }


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


@router.get("/provider")
async def provider(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await provider_status_async(db)
