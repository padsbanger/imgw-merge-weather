"""Non-blocking and duplicate-safe video generation coordination."""

from __future__ import annotations

import asyncio
import logging

from app.database import VideoRepository
from app.models import VideoGeneration, VideoMode
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
        self._tasks: set[asyncio.Task[VideoGeneration]] = set()

    async def start(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        fps: int | None = None,
    ) -> VideoGeneration:
        effective_fps = fps if fps is not None else self.service.settings.video_fps
        async with self._lock:
            active = self.repository.get_active(
                run_id=run_id, mode=mode, fps=effective_fps
            )
            if active is not None:
                raise VideoGenerationConflictError(
                    f"Video {active.video_id} is already {active.status.value}"
                )
            video = self.service.create_generation(
                run_id=run_id,
                mode=mode,
                fps=effective_fps,
            )
            task = asyncio.create_task(
                self.service.generate(video.video_id),
                name=f"imgw-video-{video.video_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._finish_task)
            return video

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
