"""Ephemeral latest-frame store for visible, consented device mirroring.

Frames are deliberately never written to Turso, disk, logs or audit detail. The
single-process Render topology keeps only the most recent JPEG per active session.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAX_FRAME_BYTES = 750_000
MAX_SESSIONS = 20
FRAME_TTL = timedelta(seconds=15)


@dataclass(slots=True)
class MirrorFrame:
    content: bytes
    captured_at: datetime
    sequence: int


class MirrorFrameStore:
    def __init__(self) -> None:
        self._frames: dict[str, MirrorFrame] = {}
        self._lock = asyncio.Lock()
        self._sequence = 0

    async def put(self, session_id: str, content: bytes) -> MirrorFrame:
        if not content or len(content) > MAX_FRAME_BYTES:
            raise ValueError(f"JPEG frame must be between 1 and {MAX_FRAME_BYTES} bytes")
        if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            raise ValueError("Mirror frame must be a complete JPEG image")
        async with self._lock:
            self._prune_locked()
            if session_id not in self._frames and len(self._frames) >= MAX_SESSIONS:
                oldest = min(self._frames, key=lambda key: self._frames[key].captured_at)
                self._frames.pop(oldest, None)
            self._sequence += 1
            frame = MirrorFrame(content=content, captured_at=datetime.now(timezone.utc), sequence=self._sequence)
            self._frames[session_id] = frame
            return frame

    async def get(self, session_id: str) -> MirrorFrame | None:
        async with self._lock:
            self._prune_locked()
            return self._frames.get(session_id)

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._frames.pop(session_id, None)

    def _prune_locked(self) -> None:
        cutoff = datetime.now(timezone.utc) - FRAME_TTL
        expired = [key for key, frame in self._frames.items() if frame.captured_at < cutoff]
        for key in expired:
            self._frames.pop(key, None)


mirror_frames = MirrorFrameStore()
