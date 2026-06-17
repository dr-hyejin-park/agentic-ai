"""Background monitoring loop that drives the engine continuously."""

from __future__ import annotations

import asyncio
import contextlib

from ..config import settings
from ..engine import engine


class Monitor:
    def __init__(self, interval: float | None = None) -> None:
        self.interval = interval or settings.monitor_interval
        self._task: asyncio.Task | None = None
        self.running = False

    async def _loop(self) -> None:
        self.running = True
        # Warm up the baselines so detectors don't fire on cold-start noise.
        for _ in range(20):
            engine.tick(inject_random=False)
        while self.running:
            try:
                engine.tick(inject_random=True)
            except Exception as exc:  # keep the loop alive
                engine._log(f"[error] monitor tick failed: {exc}")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


monitor = Monitor()
