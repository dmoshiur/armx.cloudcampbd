"""Managed, isolated PTY process running the original GPL-3.0 CMatrix binary.

The executable is started with a fixed argument allowlist (no shell, no user
input), a fresh session, a bounded TERM environment and a fixed terminal size.
Only its reconstructed screen frames leave the process; the frontend never gets
a shell, a file descriptor or arbitrary command execution.

If the binary or ncurses/PTY support is missing, ``start()`` fails with a real
reason. Nothing simulates a successful process start.
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import shutil
import signal
import struct
import subprocess
import termios
import time
from typing import Any

from app.matrix.terminal import TerminalScreen

log = logging.getLogger("armx.matrix")

LICENSE = {
    "project": "abishekvashok/cmatrix",
    "license": "GPL-3.0-or-later",
    "source": "https://github.com/abishekvashok/cmatrix",
    "debian_package": "cmatrix (Debian bookworm)",
    "notice": "/app/third_party/cmatrix/NOTICE.md",
}


class CMatrixManager:
    def __init__(self) -> None:
        self._binary = shutil.which("cmatrix")
        self._version = ""
        self._proc: asyncio.subprocess.Process | None = None
        self._master: int | None = None
        self._screen: TerminalScreen | None = None
        self._wait_task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._running = False
        self._start_failed = False
        self._error = ""
        self._last_frame = 0.0
        self._speed = 5
        self._cols = 80
        self._rows = 24

    @property
    def pty_supported(self) -> bool:
        return hasattr(os, "openpty") and hasattr(fcntl, "ioctl")

    def _detect_version(self) -> str:
        if not self._binary or self._version:
            return self._version
        try:
            result = subprocess.run(  # noqa: S603 - fixed allowlisted argv
                [self._binary, "-V"], capture_output=True, text=True, timeout=2, check=False
            )
            self._version = (result.stdout or result.stderr).strip().splitlines()[0][:120]
        except Exception:
            self._version = "cmatrix (version query unavailable)"
        return self._version

    def status(self) -> dict[str, Any]:
        binary_ok = bool(self._binary)
        reason = self._error
        if not binary_ok:
            reason = reason or (
                "The cmatrix executable is not installed in this deployment. "
                "Install the Debian 'cmatrix' package or run the provided Dockerfile, "
                "which includes the GPL-3.0 binary and its source notice."
            )
        elif not self.pty_supported:
            reason = "This host does not expose a PTY; the original terminal process cannot run."
        available = binary_ok and self.pty_supported and not self._start_failed
        return {
            "available": available,
            "running": self._running,
            "mode": "pty" if self._running else ("available" if available else "unavailable"),
            "binary": self._binary or "",
            "version": self._detect_version() if binary_ok else "",
            "pty_supported": self.pty_supported,
            "reason": "" if self._running else reason,
            "license": LICENSE,
            "implementation": "original CMatrix executable in an isolated PTY",
            "cols": self._cols,
            "rows": self._rows,
            "speed": self._speed,
            "fps": 4 + self._speed,
            "subscribers": len(self._subscribers),
        }

    async def ensure_running(self) -> bool:
        async with self._lock:
            if self._running and self._proc is not None and self._proc.returncode is None:
                return True
            if not self._binary or not self.pty_supported:
                return False
            try:
                await self._start()
            except Exception as exc:
                self._start_failed = True
                self._error = f"Could not start the real cmatrix process: {type(exc).__name__}: {exc}"
                self._push({"type": "error", "detail": self._error})
                log.error("%s", self._error)
                return False
            # Confirm the process actually stayed alive before reporting success.
            await asyncio.sleep(0.35)
            if self._proc is None or self._proc.returncode is not None:
                self._start_failed = True
                self._error = "cmatrix exited immediately after start; check TERM/ncurses in the deployment."
                self._running = False
                self._push({"type": "error", "detail": self._error})
                return False
            self._start_failed = False
            self._error = ""
            return True

    async def _start(self) -> None:
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self._rows, self._cols, 0, 0))
        os.set_blocking(master, False)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "TERM": "xterm-256color",
            "LANG": "C.UTF-8",
            "LINES": str(self._rows),
            "COLUMNS": str(self._cols),
        }
        delay = max(1, min(9, 10 - self._speed))
        argv = [self._binary, "-b", "-a", "-u", str(delay), "-C", "green"]  # noqa: S603
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self._proc = proc
        self._master = master
        self._screen = TerminalScreen(rows=self._rows, cols=self._cols)
        self._running = True
        self._last_frame = 0.0
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self._on_readable)
        self._wait_task = asyncio.create_task(self._watch(proc))
        log.info("Started original cmatrix (pid=%s, %sx%s, delay=%s)", proc.pid, self._cols, self._rows, delay)
        self._push({"type": "status", **self.status()})

    def _on_readable(self) -> None:
        if self._master is None or self._screen is None:
            return
        try:
            while True:
                chunk = os.read(self._master, 65536)
                if not chunk:
                    break
                self._screen.feed(chunk)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as exc:
            self._error = f"PTY read failed: {exc}"
            return
        now = time.monotonic()
        interval = 1.0 / (4 + self._speed)
        if self._screen.dirty and now - self._last_frame >= interval:
            self._last_frame = now
            self._screen.dirty = False
            frame = self._screen.snapshot().as_dict()
            self._push({"type": "frame", "source": "pty", **frame})

    async def _watch(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        self._running = False
        self._error = f"cmatrix exited with code {code}. No frames are being generated."
        log.warning("%s", self._error)
        self._push({"type": "error", "detail": self._error})
        await self._cleanup()

    def _push(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def configure(self, *, speed: int, density: int) -> dict[str, Any]:
        self._speed = max(1, min(10, int(speed)))
        density = max(1, min(10, int(density)))
        self._cols = 60 + density * 8
        self._rows = 18 + density * 2
        await self.stop()
        self._start_failed = False
        ok = await self.ensure_running()
        return {**self.status(), "started": ok}

    async def _cleanup(self) -> None:
        loop = asyncio.get_running_loop()
        if self._master is not None:
            try:
                loop.remove_reader(self._master)
            except Exception:
                pass
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None

    async def stop(self) -> None:
        proc = self._proc
        self._running = False
        if proc is not None and proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except (TimeoutError, asyncio.TimeoutError):
                with_kill = getattr(signal, "SIGKILL", None)
                if with_kill:
                    try:
                        os.killpg(proc.pid, with_kill)
                    except ProcessLookupError:
                        pass
        if self._wait_task is not None and not self._wait_task.done():
            self._wait_task.cancel()
        self._wait_task = None
        self._proc = None
        await self._cleanup()

    async def shutdown(self) -> None:
        await self.stop()
        self._push({"type": "error", "detail": "Matrix stream service is shutting down."})


manager = CMatrixManager()
