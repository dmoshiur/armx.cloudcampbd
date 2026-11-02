"""Background worker: housekeeping and scheduled automations.

Deliberately small and dependency-free (asyncio loop) so ``docker compose up``
gives you a working stack without a scheduler service.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Approval, PasswordResetToken, RateLimitCounter, SearchLog, Ticket
from app.registry import registry

log = logging.getLogger("armx.worker")

TICK_SECONDS = 30


async def housekeeping() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        expired = await db.execute(
            update(Approval)
            .where(Approval.status == "pending")
            .values(status="expired")
            .where(Approval.expires_at < now)
        )
        if expired.rowcount:
            log.info("expired %s stale approvals", expired.rowcount)

        await db.execute(delete(Ticket).where(Ticket.expires_at < now))
        await db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now))
        await db.execute(delete(RateLimitCounter))
        await db.execute(delete(SearchLog).where(SearchLog.created_at < now.replace(hour=0, minute=0, second=0)))
        await db.commit()


async def scheduled_automations() -> None:
    """Run time-triggered automation rules ("07:00" style) exactly once per minute."""
    from app.models import AutomationRule, SystemFlag
    from app.integrations import telecom

    now = datetime.now()
    hhmm = now.strftime("%H:%M")
    if now.second > TICK_SECONDS:
        return

    async with SessionLocal() as db:
        off = (
            await db.execute(select(SystemFlag).where(SystemFlag.key == "kill_switch"))
        ).scalar_one_or_none()
        if off is not None and off.value == "on":
            return

        rules = (
            await db.execute(select(AutomationRule).where(AutomationRule.enabled.is_(True)))
        ).scalars().all()
        for rule in rules:
            if not rule.trigger.startswith("time:"):
                continue
            if rule.trigger.split(":", 1)[1] != hhmm:
                continue
            device = await telecom.pick_device(db, rule.user_id)
            if device is None:
                continue
            if rule.action == "alarm":
                await telecom.queue_command(
                    db, user_id=rule.user_id, device=device, command="set_alarm",
                    payload={"time": hhmm, "label": rule.name},
                )
                log.info("automation %s queued an alarm for %s", rule.name, hhmm)
        await db.commit()


async def run_worker(stop: asyncio.Event | None = None) -> None:
    """Run housekeeping in-process so one Turso replica has one process owner."""
    registry.load()
    log.info("worker started (env=%s, tools=%s)", settings.ENV, len(registry.all()))
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await housekeeping()
            await scheduled_automations()
        except Exception as exc:  # pragma: no cover - keep the worker alive
            log.warning("tick failed: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    log.info("worker stopped")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s worker %(message)s")
    stop = asyncio.Event()

    def _stop(*_args) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)
    await run_worker(stop)


if __name__ == "__main__":
    asyncio.run(main())
