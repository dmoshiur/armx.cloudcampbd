"""Short-lived, single-use WebSocket/SSE stream tickets.

Browsers cannot set an Authorization header on a WebSocket or EventSource, and
putting a bearer token in a query string leaks it into logs. The authenticated
REST endpoint mints a 60-second opaque ticket instead; the stream endpoint
consumes it exactly once.
"""
from __future__ import annotations

import secrets
import time

_store: dict[str, tuple[str, float]] = {}
TTL_SECONDS = 60


def issue(user_id: str) -> str:
    now = time.time()
    for token, (_uid, expires) in list(_store.items()):
        if expires < now:
            _store.pop(token, None)
    token = secrets.token_urlsafe(32)
    _store[token] = (user_id, now + TTL_SECONDS)
    return token


def consume(token: str) -> str | None:
    entry = _store.pop(token or "", None)
    if entry is None:
        return None
    user_id, expires = entry
    return user_id if expires >= time.time() else None


def pending() -> int:
    return len(_store)
