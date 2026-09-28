"""In-process retry worker + startup reconciler (Blueprint §13.1 Jobs, §18).

Every interval: re-retain pending/failed records and re-tag retag_pending ones, with
exponential backoff up to RETRY_MAX_ATTEMPTS. On startup, heal records whose retain
reached Hindsight but whose database update was lost.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.core.logging import get_logger
from app.db.database import SessionLocal
from app.services.governed_memory_service import GovernedMemoryService

log = get_logger("worker")


class RetryWorker:
    def __init__(self, memory_service: GovernedMemoryService | None = None) -> None:
        self.memory_service = memory_service or GovernedMemoryService()
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_result: dict | None = None

    async def tick(self) -> dict:
        with SessionLocal() as db:
            result = await self.memory_service.process_outbox(db)
        self.last_result = result
        if result.get("processed"):
            log.info("retry worker synced=%s failed=%s", result.get("synced"), result.get("failed"))
        return result

    async def reconcile(self) -> int:
        with SessionLocal() as db:
            healed = await self.memory_service.reconcile(db)
        if healed:
            log.info("reconciler healed %s records", healed)
        return healed

    async def _loop(self) -> None:
        try:
            await self.reconcile()
        except Exception:
            log.exception("reconciler failed")
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("retry worker tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.retry_worker_interval_seconds)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
