"""SMTP delivery with an explicit development fallback.

In development, when SMTP is unconfigured, messages are logged and appended to
``var/outbox.log`` so password-reset can be tested end to end. In production a
missing SMTP configuration raises instead of silently dropping mail.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)


class MailNotConfigured(RuntimeError):
    pass


def _send_blocking(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if settings.SMTP_TLS:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    if not settings.SMTP_HOST:
        if settings.is_production:
            raise MailNotConfigured("SMTP_HOST is required in production")
        outbox = Path("var")
        outbox.mkdir(exist_ok=True)
        with (outbox / "outbox.log").open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- to={to} subject={subject} ---\n{body}\n")
        log.warning("SMTP not configured; wrote email for %s to var/outbox.log", to)
        return False
    await asyncio.to_thread(_send_blocking, to, subject, body)
    return True


async def send_password_reset(to: str, link: str) -> bool:
    body = (
        "Someone asked to reset the password for your A.R.M.X AI account.\n\n"
        f"Reset it here (single use, expires in {settings.PASSWORD_RESET_TTL_MINUTES} minutes):\n{link}\n\n"
        "If this was not you, ignore this email - your password stays unchanged."
    )
    return await send_email(to, "Reset your A.R.M.X AI password", body)


async def send_verification(to: str, link: str) -> bool:
    body = (
        "Confirm your email to finish setting up A.R.M.X AI.\n\n"
        f"{link}\n\nThis link is single use and expires in 24 hours."
    )
    return await send_email(to, "Confirm your A.R.M.X AI email", body)
