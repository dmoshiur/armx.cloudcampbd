"""Actionable API/provider errors with stable codes and correlation IDs.

The UI must never show a bare "Request failed". Every failure carries:
  * ``code``      — stable machine code
  * ``detail``    — a human sentence naming the failing part and the next action
  * ``hint``      — optional operator instruction
  * ``request_id``— matches the structured server log (X-Request-ID)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request


@dataclass(slots=True)
class ClassifiedError:
    code: str
    message: str
    hint: str = ""
    retryable: bool = False
    status: int = 0


_INVALID_KEY = re.compile(r"(invalid[_ -]?api[_ -]?key|unauthori[sz]ed|authentication|incorrect api key|401)", re.I)
_RATE = re.compile(r"(rate.?limit|too many requests|429|quota|resource exhausted)", re.I)
_CONTEXT = re.compile(r"(context[_ -]?(window|length)|maximum context|prompt is too long|too many tokens|413)", re.I)
_TIMEOUT = re.compile(r"(timeout|timed? ?out|deadline|504)", re.I)
_UNAVAILABLE = re.compile(r"(502|503|bad gateway|service unavailable|connection|dns|network|unreachable)", re.I)
_TOOL = re.compile(r"(tool (execution )?failed|tool_error)", re.I)
_DB = re.compile(r"(database|sqlite|turso|no such table|operationalerror)", re.I)


def classify_provider_error(raw: str, *, status: int = 0, provider: str = "") -> ClassifiedError:
    """Map a provider/HTTP failure to an actionable, stable error code."""
    text = raw or "The provider did not return a usable response."
    label = f"{provider}: " if provider else ""
    if _INVALID_KEY.search(text) or status == 401:
        return ClassifiedError(
            "invalid_api_credentials",
            label + "The provider rejected the API key. Check Admin → Models and rotate the stored credential.",
            "Open Admin → Models, edit the provider and re-enter the key.",
        )
    if _RATE.search(text) or status == 429:
        return ClassifiedError(
            "rate_limit_exceeded",
            label + "The provider rate limit or quota was reached. A retry or fallback route is being tried.",
            "Add a second enabled model or wait for the provider quota to reset.",
            retryable=True,
        )
    if _CONTEXT.search(text):
        return ClassifiedError(
            "context_window_exceeded",
            label + "The conversation exceeds this model's context window. Start a new chat or enable summarisation.",
            "A.R.M.X automatically summarises older turns when the context budget is reached.",
        )
    if _TIMEOUT.search(text):
        return ClassifiedError(
            "request_timed_out",
            label + "The provider did not answer before the deadline.",
            "Check the provider status in Admin → Models, then retry.",
            retryable=True,
        )
    if _UNAVAILABLE.search(text) or status in (502, 503, 504):
        return ClassifiedError(
            "provider_unavailable",
            label + "The AI provider is unreachable right now.",
            "Check /api/health/providers and the provider's status page.",
            retryable=True,
        )
    if _TOOL.search(text):
        return ClassifiedError(
            "tool_execution_failed",
            label + "A registered tool failed during execution. The result is shown in the execution details.",
            "Inspect Activity Logs for the tool error before retrying.",
        )
    if _DB.search(text):
        return ClassifiedError(
            "database_unavailable",
            "The application database is unavailable. No data was discarded.",
            "Check /api/health and the Turso credentials on the host.",
            retryable=True,
        )
    return ClassifiedError(
        "provider_error",
        label + text[:400],
        "Check Admin → Models and test the route; the request ID matches the server log.",
        retryable=status >= 500,
        status=status,
    )


def error_payload(
    code: str,
    message: str,
    *,
    hint: str = "",
    request_id: str = "",
    retryable: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "detail": message, "request_id": request_id}
    if hint:
        payload["hint"] = hint
    if retryable:
        payload["retryable"] = True
    payload.update(extra)
    return payload


def api_error(
    status_code: int,
    code: str,
    message: str,
    request: Request,
    *,
    hint: str = "",
    retryable: bool = False,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> HTTPException:
    rid = getattr(request.state, "request_id", "")
    return HTTPException(
        status_code=status_code,
        detail=error_payload(code, message, hint=hint, request_id=rid, retryable=retryable, **extra),
        headers=headers,
    )


GATEWAY_HINTS = {
    "approval_expired": "Request a new approval; the previous one is never reused.",
    "approval_wrong_session": "Your sign-in session was renewed. Request a new approval for the same action.",
    "approval_reused": "This approval was already used. No duplicate execution was performed.",
    "denied": "The security gateway blocked this action. Check Activity Logs for the reason.",
    "unknown_tool": "The model requested a tool that is not registered.",
}
