"""Read-only IMAP mail access.

Read-only by construction: we never issue STORE/COPY/EXPUNGE flags, and bodies are
truncated. Mail content is untrusted DATA for the planner.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
from email.header import decode_header
from typing import Any

from app.core.config import settings
from app.integrations.base import IntegrationNotConfigured, IntegrationStatus

MAX_BODY_CHARS = 1500


def status() -> IntegrationStatus:
    return IntegrationStatus(
        provider="imap", configured=bool(settings.IMAP_HOST and settings.IMAP_USER and settings.IMAP_PASSWORD)
    )


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")[:MAX_BODY_CHARS]
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")[:MAX_BODY_CHARS]


def _fetch_blocking(limit: int, mailbox: str, unseen_only: bool) -> list[dict[str, Any]]:
    client = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT) if settings.IMAP_PORT == 993 else imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT)
    try:
        client.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        client.select(mailbox, readonly=True)  # read-only: no flags are changed
        criteria = "UNSEEN" if unseen_only else "ALL"
        typ, data = client.search(None, criteria)
        if typ != "OK":
            return []
        ids = data[0].split()[-limit:]
        out: list[dict[str, Any]] = []
        for msg_id in reversed(ids):
            typ, raw = client.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            out.append(
                {
                    "from": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                    "preview": " ".join(_extract_body(msg).split())[:400],
                }
            )
        return out
    finally:
        try:
            client.logout()
        except Exception:  # pragma: no cover
            pass


async def read_inbox(limit: int = 5, mailbox: str = "INBOX", unseen_only: bool = False) -> list[dict[str, Any]]:
    if not status().configured:
        raise IntegrationNotConfigured(
            "imap", "Set IMAP_HOST, IMAP_USER and IMAP_PASSWORD to enable read-only mail access."
        )
    return await asyncio.to_thread(_fetch_blocking, max(1, min(limit, 20)), mailbox, unseen_only)
