"""Signed, short-lived preview tokens.

A preview iframe cannot send an Authorization header, so access is granted with a
capability token bound to one project and a short expiry. It carries no user
credentials and cannot be reused for any API route.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.core.config import settings

PREVIEW_TTL_SECONDS = 3600


def _sign(payload: str) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue(project_id: str, ttl: int = PREVIEW_TTL_SECONDS) -> str:
    body = json.dumps({"p": project_id, "e": int(time.time()) + ttl}, separators=(",", ":"))
    raw = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def verify(token: str) -> str | None:
    if not token or token.count(".") != 1:
        return None
    raw, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _sign(raw)):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None
    if int(data.get("e", 0)) < int(time.time()):
        return None
    return str(data.get("p", "")) or None
