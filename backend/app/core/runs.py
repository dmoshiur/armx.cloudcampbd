"""Process-local cancellation registry for in-flight assistant runs.

Runs are single-process in the supported deployment (one Render instance owns
the embedded Turso replica). An Event is registered as soon as a run is created
so the browser's Stop button can cancel a completion that has not returned yet.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress


_events: dict[str, asyncio.Event] = {}


def register(run_id: str) -> asyncio.Event:
    event = asyncio.Event()
    _events[run_id] = event
    return event


def get(run_id: str) -> asyncio.Event | None:
    return _events.get(run_id)


def stop(run_id: str) -> bool:
    event = _events.get(run_id)
    if event is None:
        return False
    event.set()
    return True


def clear(run_id: str) -> None:
    _events.pop(run_id, None)


async def wait_or_cancel(awaitable, event: asyncio.Event | None):
    """Race an adapter completion against a stop request; cancel on stop."""
    if event is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    stop_task = asyncio.ensure_future(event.wait())
    done, pending = await asyncio.wait({task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for item in pending:
        item.cancel()
        with suppress(asyncio.CancelledError):
            await item
    if stop_task in done and task not in done:
        raise asyncio.CancelledError()
    return task.result()
