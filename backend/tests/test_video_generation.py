import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database import Database, ForecastRepository, VideoRepository
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)
from app.services.video_generation import (
    VideoGenerationConflictError,
    VideoGenerationCoordinator,
)

NOW = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


class StubVideoService:
    def __init__(self, repository: VideoRepository) -> None:
        self.repository = repository
        self.settings = SimpleNamespace(video_fps=5)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def create_generation(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        fps: int,
        start_frame_index: int | None,
        end_frame_index: int | None,
        timestamp_overlay: bool,
    ) -> VideoGeneration:
        video = VideoGeneration(
            video_id="video_coord001",
            run_id=run_id,
            created_at=NOW,
            updated_at=NOW,
            mode=mode,
            fps=fps,
            crf=20,
            preset="medium",
            output_filename="video_coord001.mp4",
            start_frame_index=start_frame_index or 0,
            end_frame_index=end_frame_index,
            timestamp_overlay=timestamp_overlay,
        )
        self.repository.upsert(video)
        return video

    async def generate(self, video_id: str) -> VideoGeneration:
        self.started.set()
        await self.release.wait()
        video = self.repository.get(video_id)
        assert video is not None
        video.status = VideoGenerationStatus.COMPLETED
        video.width = 1700
        video.height = 1600
        video.duration_seconds = 1
        video.size_bytes = 2048
        self.repository.upsert(video)
        return video


def repositories(tmp_path: Path) -> VideoRepository:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    ForecastRepository(database).upsert_run(
        ForecastRun(
            run_id="merge_coord",
            discovered_at=NOW,
            updated_at=NOW,
            requested_start_time=NOW,
            interval_minutes=10,
            forecast_hours=8,
            allow_missing_frames=False,
            minimum_frame_coverage=0.9,
            status=ForecastRunStatus.COMPLETED,
        )
    )
    return VideoRepository(database)


@pytest.mark.asyncio
async def test_video_coordinator_runs_in_background_and_rejects_duplicate(
    tmp_path: Path,
) -> None:
    repository = repositories(tmp_path)
    service = StubVideoService(repository)
    coordinator = VideoGenerationCoordinator(service=service, repository=repository)

    pending = await coordinator.start(
        run_id="merge_coord", mode=VideoMode.SOURCE, fps=5
    )
    await service.started.wait()

    assert pending.status == VideoGenerationStatus.PENDING
    with pytest.raises(VideoGenerationConflictError, match="already pending"):
        await coordinator.start(run_id="merge_coord", mode=VideoMode.SOURCE, fps=5)

    service.release.set()
    for _ in range(10):
        completed = repository.get(pending.video_id)
        if completed is not None and completed.status == VideoGenerationStatus.COMPLETED:
            break
        await asyncio.sleep(0)
    assert completed is not None
    assert completed.status == VideoGenerationStatus.COMPLETED


@pytest.mark.asyncio
async def test_video_coordinator_cancels_active_generation_on_shutdown(
    tmp_path: Path,
) -> None:
    repository = repositories(tmp_path)
    service = StubVideoService(repository)
    coordinator = VideoGenerationCoordinator(service=service, repository=repository)
    await coordinator.start(run_id="merge_coord", mode=VideoMode.SOURCE, fps=5)
    await service.started.wait()

    await coordinator.shutdown()
