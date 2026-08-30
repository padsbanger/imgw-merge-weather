"""Non-blocking and duplicate-safe video generation coordination."""

from __future__ import annotations

import asyncio
import logging

from app.database import VideoRepository
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoInterpolation,
    VideoMode,
    VideoSmoothing,
)
from app.video import VideoGenerationService

LOGGER = logging.getLogger(__name__)


class VideoGenerationConflictError(RuntimeError):
    """Raised when the same run/mode/FPS combination is already active."""


class VideoGenerationCoordinator:
    def __init__(
        self,
        *,
        service: VideoGenerationService,
        repository: VideoRepository,
    ) -> None:
        self.service = service
        self.repository = repository
        self._lock = asyncio.Lock()
        self._render_slots = asyncio.Semaphore(
            self.service.settings.video_max_concurrent_renders
        )
        self._tasks: set[asyncio.Task[VideoGeneration]] = set()

    async def start(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        source_fps: int | None = None,
        output_fps: int | None = None,
        interpolation: VideoSmoothing | None = None,
        start_frame_index: int | None = None,
        end_frame_index: int | None = None,
        timestamp_overlay: bool = False,
    ) -> VideoGeneration:
        effective_source_fps = (
            source_fps
            if source_fps is not None
            else self.service.settings.video_source_fps
        )
        effective_output_fps = (
            output_fps
            if output_fps is not None
            else self.service.settings.video_output_fps
        )
        effective_interpolation = interpolation or VideoSmoothing(
            self.service.settings.video_interpolation
        )
        stored_interpolation = VideoInterpolation(effective_interpolation.value)
        async with self._lock:
            active = self.repository.get_active(
                run_id=run_id,
                mode=mode,
                source_fps=effective_source_fps,
                output_fps=effective_output_fps,
                interpolation=stored_interpolation,
            )
            if active is not None:
                raise VideoGenerationConflictError(
                    f"Video {active.video_id} is already {active.status.value}"
                )
            video = self.service.create_generation(
                run_id=run_id,
                mode=mode,
                source_fps=effective_source_fps,
                output_fps=effective_output_fps,
                interpolation=effective_interpolation,
                start_frame_index=start_frame_index,
                end_frame_index=end_frame_index,
                timestamp_overlay=timestamp_overlay,
            )
            task = asyncio.create_task(
                self._generate(video.video_id),
                name=f"imgw-video-{video.video_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._finish_task)
            return video

    async def _generate(self, video_id: str) -> VideoGeneration:
        async with self._render_slots:
            return await self.service.generate(video_id)

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _finish_task(self, task: asyncio.Task[VideoGeneration]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                LOGGER.error("event=video_task_failed error=%s", error)


async def ensure_forecast_video(
    run: ForecastRun | None,
    *,
    enabled: bool,
    repository: VideoRepository,
    coordinator: VideoGenerationCoordinator,
) -> VideoGeneration | None:
    """Enqueue one default video when a completed forecast has no usable generation."""

    if not enabled or run is None or run.status != ForecastRunStatus.COMPLETED:
        return None

    existing = next(
        (
            video
            for video in repository.list(limit=1_000, run_id=run.run_id)
            if video.status
            in {
                VideoGenerationStatus.PENDING,
                VideoGenerationStatus.RENDERING,
                VideoGenerationStatus.COMPLETED,
            }
        ),
        None,
    )
    if existing is not None:
        LOGGER.info(
            "run=%s video=%s event=automatic_video_skipped reason=video_available",
            run.run_id,
            existing.video_id,
        )
        return existing

    try:
        video = await coordinator.start(run_id=run.run_id, mode=VideoMode.SOURCE)
    except VideoGenerationConflictError:
        # Another request won the race after the repository check.
        LOGGER.info(
            "run=%s event=automatic_video_skipped reason=generation_active",
            run.run_id,
        )
        return None
    LOGGER.info(
        "run=%s video=%s event=automatic_video_enqueued",
        run.run_id,
        video.video_id,
    )
    return video
