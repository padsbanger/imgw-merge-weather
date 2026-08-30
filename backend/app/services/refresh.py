"""Non-blocking, duplicate-safe manual forecast refresh coordination."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import Settings
from app.database import ForecastRepository
from app.forecast import (
    CompleteSequenceProbe,
    LatestFrameNotFoundError,
    probe_latest_complete_sequence,
)
from app.imgw_client import ImgwClientError, ImgwMergeClient
from app.models import ForecastRun
from app.services.ingestion import ForecastIngestionService

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    status: str
    run: ForecastRun | None = None
    reason: str | None = None
    error: str | None = None

    @classmethod
    def from_run(cls, run: ForecastRun) -> RefreshOutcome:
        return cls(status=run.status.value, run=run, error=run.error)


RefreshOperation = Callable[[], Awaitable[ForecastRun | RefreshOutcome]]


async def ingest_latest_forecast(
    settings: Settings,
    repository: ForecastRepository,
) -> RefreshOutcome:
    client = ImgwMergeClient(
        base_url=settings.base_url,
        user_agent=settings.user_agent,
        connect_timeout_seconds=settings.connect_timeout_seconds,
        read_timeout_seconds=settings.read_timeout_seconds,
        max_retries=settings.max_retries,
        backoff_seconds=settings.retry_backoff_seconds,
        concurrency=settings.frame_concurrency,
        min_body_size=settings.min_frame_bytes,
        min_width=settings.min_frame_width,
        min_height=settings.min_frame_height,
    )
    async with client:
        discovered_at = datetime.now(UTC)
        try:
            latest_probe = await probe_latest_complete_sequence(
                client,
                now=discovered_at,
                horizon_hours=settings.forecast_hours,
                lookback_hours=settings.forecast_lookback_hours,
                interval_minutes=settings.frame_interval_minutes,
                max_fallback_steps=settings.max_start_fallback_steps,
            )
        except (ImgwClientError, LatestFrameNotFoundError) as error:
            LOGGER.error("event=refresh_probe_failed error=%s", error)
            return RefreshOutcome(status="failed", error=str(error))
        unchanged_run = _find_unchanged_run(repository, latest_probe)
        if unchanged_run is not None:
            LOGGER.info(
                "run=%s event=refresh_skipped reason=remote_unchanged "
                "resolved_start=%s",
                unchanged_run.run_id,
                latest_probe.resolved_start_time.isoformat(),
            )
            return RefreshOutcome(
                status="skipped",
                run=unchanged_run,
                reason="Newest remote forecast is already stored",
            )

        service = ForecastIngestionService(
            client=client,
            data_dir=settings.data_dir,
            interval_minutes=settings.frame_interval_minutes,
            forecast_hours=settings.forecast_hours,
            lookback_hours=settings.forecast_lookback_hours,
            max_start_fallback_steps=settings.max_start_fallback_steps,
            allow_missing_frames=settings.allow_missing_frames,
            minimum_frame_coverage=settings.min_frame_coverage,
            repository=repository,
        )
        run = await service.ingest(now=discovered_at, latest_probe=latest_probe)
        return RefreshOutcome.from_run(run)


def _find_unchanged_run(
    repository: ForecastRepository,
    probe: CompleteSequenceProbe,
) -> ForecastRun | None:
    if not probe.prefetched_frames:
        return None
    latest = repository.get_latest_completed_run()
    if latest is None or latest.resolved_start_time != probe.resolved_start_time:
        return None

    frames_by_time = {frame.forecast_time: frame for frame in latest.frames}
    for forecast_time, downloaded in probe.prefetched_frames.items():
        existing = frames_by_time.get(forecast_time)
        remote_hash = hashlib.sha256(downloaded.content).hexdigest()
        if existing is None or existing.sha256 != remote_hash:
            return None
    return latest


class RefreshCoordinator:
    """Own at most one refresh task while keeping request handling responsive."""

    def __init__(
        self,
        operation: RefreshOperation,
        *,
        repository: ForecastRepository | None = None,
    ) -> None:
        self._operation = operation
        self._repository = repository
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[RefreshOutcome] | None = None
        self._last_refresh_at = self._read_datetime_state("refresh.last_finished_at")
        self._last_refresh_status = self._read_state("refresh.last_status")
        self._last_imgw_error = self._read_state("refresh.last_imgw_error")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_refresh_at(self) -> datetime | None:
        return self._last_refresh_at

    @property
    def last_refresh_status(self) -> str | None:
        return self._last_refresh_status

    @property
    def last_imgw_error(self) -> str | None:
        return self._last_imgw_error

    async def start(self, *, origin: str = "manual") -> bool:
        async with self._lock:
            if self.is_running:
                LOGGER.info("event=refresh_skipped reason=overlap origin=%s", origin)
                return False
            self._task = asyncio.create_task(
                self._run_operation(),
                name="imgw-forecast-refresh",
            )
            self._task.add_done_callback(self._consume_result)
            LOGGER.info("event=refresh_started origin=%s", origin)
            return True

    async def shutdown(self) -> None:
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            LOGGER.info("event=refresh_cancelled reason=application_shutdown")

    async def _run_operation(self) -> RefreshOutcome:
        try:
            result = await self._operation()
            outcome = (
                result if isinstance(result, RefreshOutcome) else RefreshOutcome.from_run(result)
            )
            run_id = outcome.run.run_id if outcome.run is not None else "none"
            event = "refresh_skipped" if outcome.status == "skipped" else "refresh_finished"
            LOGGER.info(
                "run=%s event=%s status=%s reason=%s",
                run_id,
                event,
                outcome.status,
                outcome.reason or "none",
            )
            self._record_result(outcome.status, outcome.error)
            return outcome
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOGGER.exception("event=refresh_failed unexpected=true")
            self._record_result("failed", str(error) or "Unexpected forecast refresh failure")
            raise

    @staticmethod
    def _consume_result(task: asyncio.Task[RefreshOutcome]) -> None:
        if not task.cancelled():
            task.exception()

    def _record_result(self, status: str, error: str | None) -> None:
        self._last_refresh_at = datetime.now(UTC)
        self._last_refresh_status = status
        self._last_imgw_error = error
        if self._repository is None:
            return
        timestamp = self._last_refresh_at.isoformat().replace("+00:00", "Z")
        self._repository.set_application_state("refresh.last_finished_at", timestamp)
        self._repository.set_application_state("refresh.last_status", status)
        self._repository.set_application_state("refresh.last_imgw_error", error or "")

    def _read_state(self, key: str) -> str | None:
        if self._repository is None:
            return None
        value = self._repository.get_application_state(key)
        return value or None

    def _read_datetime_state(self, key: str) -> datetime | None:
        value = self._read_state(key)
        if value is None:
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            LOGGER.warning("event=refresh_state_invalid key=%s value=%s", key, value)
            return None
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return None
        return timestamp.astimezone(UTC)
