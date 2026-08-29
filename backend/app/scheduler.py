"""Lightweight APScheduler integration for automatic forecast refreshes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, JobSubmissionEvent
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings

LOGGER = logging.getLogger(__name__)
REFRESH_JOB_ID = "imgw-merge-automatic-refresh"


class RefreshStarter(Protocol):
    async def start(self, *, origin: str = "manual") -> bool: ...


class AutomaticRefreshScheduler:
    """Schedule one conservative refresh trigger in the application's event loop."""

    def __init__(self, settings: Settings, coordinator: RefreshStarter) -> None:
        self.settings = settings
        self.coordinator = coordinator
        self._scheduler = AsyncIOScheduler(timezone=UTC)
        self._scheduler.add_listener(self._log_max_instances_skip, EVENT_JOB_MAX_INSTANCES)
        self._job: Job | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return self.settings.scheduler_enabled

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        return "running" if self._started else "stopped"

    @property
    def next_run_at(self) -> datetime | None:
        if self._job is None or not self._started:
            return None
        next_run = self._job.next_run_time
        return next_run.astimezone(UTC) if next_run is not None else None

    def start(self) -> None:
        if not self.enabled:
            LOGGER.info("event=scheduler_disabled")
            return
        trigger = CronTrigger.from_crontab(self.settings.scheduler_cron, timezone=UTC)
        self._job = self._scheduler.add_job(
            self.run_scheduled_refresh,
            trigger=trigger,
            id=REFRESH_JOB_ID,
            name="IMGW MERGE automatic refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=self.settings.scheduler_misfire_grace_seconds,
        )
        self._scheduler.start()
        self._started = True
        LOGGER.info(
            "event=scheduler_started cron=%s next_run_at=%s",
            self.settings.scheduler_cron,
            self.next_run_at.isoformat() if self.next_run_at is not None else "none",
        )

    async def run_scheduled_refresh(self) -> None:
        if await self.coordinator.start(origin="scheduled"):
            LOGGER.info("event=scheduled_refresh_accepted")
        else:
            LOGGER.info("event=scheduled_refresh_skipped reason=refresh_in_progress")

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            LOGGER.info("event=scheduler_stopped")

    @staticmethod
    def _log_max_instances_skip(event: JobSubmissionEvent) -> None:
        LOGGER.info(
            "event=scheduled_refresh_skipped reason=max_instances job=%s",
            event.job_id,
        )
