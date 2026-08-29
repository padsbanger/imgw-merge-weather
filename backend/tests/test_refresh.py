import asyncio
import hashlib
from datetime import UTC, datetime

import pytest

from app.database import Database, ForecastRepository
from app.forecast import CompleteSequenceProbe
from app.imgw_client import DownloadedFrame, FrameMetadata
from app.models import (
    ForecastFrame,
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
)
from app.services.refresh import RefreshCoordinator, RefreshOutcome, _find_unchanged_run


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


def downloaded_frame(timestamp: datetime, content: bytes) -> DownloadedFrame:
    return DownloadedFrame(
        metadata=FrameMetadata(
            forecast_time=timestamp,
            source_url=f"https://cmm.imgw.pl/{timestamp:%H%M}.jpg",
            content_type="image/jpeg",
            size_bytes=len(content),
            width=1700,
            height=1600,
            image_format="JPEG",
        ),
        content=content,
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


@pytest.mark.asyncio
async def test_skipped_refresh_is_recorded_as_successful_remote_check(tmp_path) -> None:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    repository = ForecastRepository(database)

    async def operation() -> RefreshOutcome:
        return RefreshOutcome(
            status="skipped",
            run=make_run(),
            reason="Newest remote forecast is already stored",
        )

    coordinator = RefreshCoordinator(operation, repository=repository)
    assert await coordinator.start(origin="scheduled") is True
    for _ in range(10):
        if not coordinator.is_running:
            break
        await asyncio.sleep(0)

    assert coordinator.last_refresh_status == "skipped"
    assert coordinator.last_refresh_at is not None
    assert coordinator.last_imgw_error is None


def test_remote_boundary_hashes_prevent_duplicate_completed_runs(tmp_path) -> None:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    repository = ForecastRepository(database)
    start = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    end = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
    start_content = b"current-start-frame"
    end_content = b"current-end-frame"
    run = make_run()
    run.resolved_start_time = start
    run.forecast_end_time = end
    run.expected_frames = 2
    run.downloaded_frames = 2
    run.coverage = 1
    run.frames = [
        ForecastFrame(
            frame_index=index,
            forecast_time=timestamp,
            source_url=f"https://cmm.imgw.pl/{index}.jpg",
            local_filename=f"frames/frame_{index:03d}.jpg",
            width=1700,
            height=1600,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            validation_status=FrameValidationStatus.VALID,
        )
        for index, (timestamp, content) in enumerate(
            ((start, start_content), (end, end_content))
        )
    ]
    repository.upsert_run(run)
    probe = CompleteSequenceProbe(
        expected_start_time=start,
        resolved_start_time=start,
        fallback_steps=0,
        attempted_start_times=(start,),
        prefetched_frames={
            start: downloaded_frame(start, start_content),
            end: downloaded_frame(end, end_content),
        },
    )

    assert _find_unchanged_run(repository, probe) == run

    revised_probe = CompleteSequenceProbe(
        expected_start_time=start,
        resolved_start_time=start,
        fallback_steps=0,
        attempted_start_times=(start,),
        prefetched_frames={
            start: downloaded_frame(start, b"revised-start-frame"),
            end: downloaded_frame(end, end_content),
        },
    )
    assert _find_unchanged_run(repository, revised_probe) is None
