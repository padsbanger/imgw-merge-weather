import asyncio
from datetime import UTC, datetime

import pytest

from app.database import Database, ForecastRepository
from app.models import ForecastRun, ForecastRunStatus
from app.services.refresh import RefreshCoordinator


def make_run() -> ForecastRun:
    timestamp = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    return ForecastRun(
        run_id="merge_refresh",
        discovered_at=timestamp,
        updated_at=timestamp,
        requested_start_time=timestamp,
        interval_minutes=10,
        forecast_hours=8,
        allow_missing_frames=False,
        minimum_frame_coverage=0.9,
        status=ForecastRunStatus.COMPLETED,
    )


@pytest.mark.asyncio
async def test_refresh_coordinator_runs_in_background_and_prevents_overlap() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def operation() -> ForecastRun:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return make_run()

    coordinator = RefreshCoordinator(operation)

    assert await coordinator.start() is True
    await started.wait()
    assert coordinator.is_running is True
    assert await coordinator.start() is False
    assert calls == 1

    release.set()
    for _ in range(10):
        if not coordinator.is_running:
            break
        await asyncio.sleep(0)

    assert coordinator.is_running is False
    assert await coordinator.start() is True
    await asyncio.sleep(0)
    assert calls == 2


@pytest.mark.asyncio
async def test_refresh_coordinator_cancels_active_work_on_shutdown() -> None:
    started = asyncio.Event()

    async def operation() -> ForecastRun:
        started.set()
        await asyncio.Event().wait()
        return make_run()

    coordinator = RefreshCoordinator(operation)
    await coordinator.start()
    await started.wait()

    await coordinator.shutdown()

    assert coordinator.is_running is False


@pytest.mark.asyncio
async def test_refresh_result_and_imgw_error_survive_coordinator_restart(tmp_path) -> None:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    repository = ForecastRepository(database)
    failed_run = make_run()
    failed_run.status = ForecastRunStatus.FAILED
    failed_run.error = "IMGW returned HTTP 503"

    async def operation() -> ForecastRun:
        return failed_run

    coordinator = RefreshCoordinator(operation, repository=repository)
    assert await coordinator.start() is True
    for _ in range(10):
        if not coordinator.is_running:
            break
        await asyncio.sleep(0)

    restarted = RefreshCoordinator(operation, repository=repository)
    assert restarted.last_refresh_at is not None
    assert restarted.last_refresh_status == "failed"
    assert restarted.last_imgw_error == "IMGW returned HTTP 503"
