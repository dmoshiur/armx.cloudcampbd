"""Authenticated streaming of the real CMatrix PTY terminal frames.

Transport order: WebSocket (``/api/matrix/ws``), with SSE (``/api/matrix/stream``)
as a fallback for proxies that do not forward upgrades. Both use one-use tickets.
The browser falls back to the vendored MIT JS port only after reporting that the
original executable is unavailable; it never claims the binary ran.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.deps import get_auth_context, require_admin
from app.matrix import manager
from app.matrix.tickets import consume, issue, pending

router = APIRouter(prefix="/matrix", tags=["matrix"])
log = logging.getLogger("armx.matrix.api")


class MatrixControl(BaseModel):
    speed: int = Field(default=5, ge=1, le=10)
    density: int = Field(default=5, ge=1, le=10)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.get("/status")
async def matrix_status() -> dict[str, Any]:
    """Public capability status. Contains no secrets and grants no access."""
    return {
        **manager.status(),
        "transports": ["websocket", "sse", "mit_js_port_fallback"],
        "pending_tickets": pending(),
        "reduced_motion": "handled entirely by the browser renderer",
    }


@router.post("/ticket")
async def matrix_ticket(ctx=Depends(get_auth_context)) -> dict[str, Any]:
    from app.core.deps import AuthContext

    auth: AuthContext = ctx
    token = issue(auth.user.id)
    return {
        "ticket": token,
        "expires_in": 60,
        "websocket_path": f"/api/matrix/ws?ticket={token}",
        "sse_path": f"/api/matrix/stream?ticket={token}",
    }


@router.post("/configure")
async def configure_matrix(
    payload: MatrixControl,
    _admin=Depends(require_admin),
) -> dict[str, Any]:
    """Operator-level PTY speed/density. Per-user opacity is applied in the browser."""
    result = await manager.configure(speed=payload.speed, density=payload.density)
    return result


@router.websocket("/ws")
async def matrix_ws(websocket: WebSocket, ticket: str = "") -> None:
    user_id = consume(ticket)
    if user_id is None:
        await websocket.close(code=4401, reason="Missing or expired stream ticket")
        return
    await websocket.accept()
    started = await manager.ensure_running()
    if not started:
        await websocket.send_json(
            {
                "type": "error",
                "detail": manager.status()["reason"] or "The real CMatrix process is unavailable.",
                "status": manager.status(),
                "fallback": "mit_js_port",
            }
        )
        await websocket.close(code=4404)
        return
    queue = manager.subscribe()
    try:
        await websocket.send_json({"type": "status", **manager.status()})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") == "error":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport boundary
        log.debug("Matrix WebSocket closed: %s", exc)
    finally:
        manager.unsubscribe(queue)


@router.get("/stream")
async def matrix_sse(ticket: str = "") -> StreamingResponse:
    user_id = consume(ticket)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Missing or expired stream ticket")

    async def generate() -> AsyncIterator[str]:
        started = await manager.ensure_running()
        if not started:
            yield _sse(
                {
                    "type": "error",
                    "detail": manager.status()["reason"] or "The real CMatrix process is unavailable.",
                    "status": manager.status(),
                    "fallback": "mit_js_port",
                }
            )
            return
        queue = manager.subscribe()
        yield _sse({"type": "status", **manager.status()})
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event)
                if event.get("type") == "error":
                    break
        finally:
            manager.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
