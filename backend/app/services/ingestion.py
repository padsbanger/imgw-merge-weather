"""Complete IMGW MERGE forecast-run ingestion and manifest persistence."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.database import ForecastRepository
from app.forecast import (
    CompleteSequenceProbe,
    LatestFrameNotFoundError,
    build_frame_times,
    floor_to_interval,
    format_utc_iso,
    probe_latest_complete_sequence,
    to_utc,
)
from app.imgw_client import (
    DownloadedFrame,
    FrameUnavailableError,
    ImgwClientError,
    ImgwMergeClient,
)
from app.models import (
    ForecastFrame,
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
)
from app.persistence import write_forecast_manifest

LOGGER = logging.getLogger(__name__)
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,95}$")


@dataclass(frozen=True, slots=True)
class FrameDownloadResult:
    frame_index: int
    status: FrameValidationStatus
    downloaded_frame: DownloadedFrame | None = None
    error: str | None = None


def generate_run_id(discovered_at: datetime) -> str:
    timestamp = to_utc(discovered_at).strftime("%Y%m%dt%H%M%Sz")
    return f"merge_{timestamp}_{uuid4().hex[:8]}"


def safe_run_directory(data_dir: Path, run_id: str) -> Path:
    """Resolve a path-safe, unique run directory inside the configured data root."""

    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError(f"Unsafe forecast run ID: {run_id!r}")

    data_root = Path(data_dir).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    runs_root = (data_root / "runs").resolve()
    if not runs_root.is_relative_to(data_root):
        raise ValueError("Forecast runs directory resolves outside the configured data directory")
    runs_root.mkdir(parents=True, exist_ok=True)

    run_directory = (runs_root / run_id).resolve()
    if not run_directory.is_relative_to(runs_root):
        raise ValueError("Forecast run directory resolves outside the runs directory")
    run_directory.mkdir(parents=False, exist_ok=False)
    return run_directory


class ForecastIngestionService:
    """Collect one immutable local snapshot of a complete MERGE forecast sequence."""

    def __init__(
        self,
        *,
        client: ImgwMergeClient,
        data_dir: Path,
        interval_minutes: int = 10,
        forecast_hours: int = 8,
        lookback_hours: int = 0,
        max_start_fallback_steps: int = 6,
        allow_missing_frames: bool = False,
        minimum_frame_coverage: float = 0.90,
        run_id_factory: Callable[[datetime], str] = generate_run_id,
        repository: ForecastRepository | None = None,
    ) -> None:
        if not 0 <= minimum_frame_coverage <= 1:
            raise ValueError("Minimum frame coverage must be between 0 and 1")

        self.client = client
        self.data_dir = Path(data_dir)
        self.interval_minutes = interval_minutes
        self.forecast_hours = forecast_hours
        self.lookback_hours = lookback_hours
        self.max_start_fallback_steps = max_start_fallback_steps
        self.allow_missing_frames = allow_missing_frames
        self.minimum_frame_coverage = minimum_frame_coverage
        self.run_id_factory = run_id_factory
        self.repository = repository

    async def ingest(
        self,
        *,
        start_time: datetime | None = None,
        now: datetime | None = None,
        latest_probe: CompleteSequenceProbe | None = None,
    ) -> ForecastRun:
        if start_time is not None and latest_probe is not None:
            raise ValueError("Explicit start time and latest probe are mutually exclusive")
        discovered_at = to_utc(now or datetime.now(UTC))
        requested_start = (
            to_utc(start_time)
            if start_time is not None
            else (
                latest_probe.expected_start_time
                if latest_probe is not None
                else floor_to_interval(discovered_at, self.interval_minutes)
            )
        )
        run_id = self.run_id_factory(discovered_at)
        run_directory = safe_run_directory(self.data_dir, run_id)
        frames_directory = run_directory / "frames"
        frames_directory.mkdir()
        run = ForecastRun(
            run_id=run_id,
            discovered_at=discovered_at,
            updated_at=discovered_at,
            requested_start_time=requested_start,
            interval_minutes=self.interval_minutes,
            forecast_hours=self.forecast_hours,
            allow_missing_frames=self.allow_missing_frames,
            minimum_frame_coverage=self.minimum_frame_coverage,
        )
        self._persist_run(run, run_directory)

        try:
            prefetched_frames: dict[datetime, DownloadedFrame] = {}
            if latest_probe is not None:
                run.status = ForecastRunStatus.PROBING
                self._persist_run(run, run_directory)
                resolved_start = latest_probe.resolved_start_time
                prefetched_frames = latest_probe.prefetched_frames
            elif start_time is None:
                run.status = ForecastRunStatus.PROBING
                self._persist_run(run, run_directory)
                probe = await probe_latest_complete_sequence(
                    self.client,
                    now=discovered_at,
                    horizon_hours=self.forecast_hours,
                    lookback_hours=self.lookback_hours,
                    interval_minutes=self.interval_minutes,
                    max_fallback_steps=self.max_start_fallback_steps,
                )
                resolved_start = probe.resolved_start_time
                prefetched_frames = probe.prefetched_frames
            else:
                resolved_start = requested_start

            frame_times = build_frame_times(
                resolved_start,
                horizon_hours=self.forecast_hours,
                lookback_hours=self.lookback_hours,
                interval_minutes=self.interval_minutes,
            )
            run.resolved_start_time = resolved_start
            run.forecast_end_time = frame_times[-1]
            run.expected_frames = len(frame_times)
            run.frames = [
                ForecastFrame(
                    frame_index=index,
                    forecast_time=forecast_time,
                    source_url=self.client.frame_url(forecast_time),
                    local_filename=f"frames/frame_{index:03d}.jpg",
                )
                for index, forecast_time in enumerate(frame_times)
            ]
            run.status = ForecastRunStatus.DOWNLOADING
            self._persist_run(run, run_directory)

            tasks = [
                asyncio.create_task(
                    self._download_frame(
                        run.frames[index],
                        run_directory,
                        prefetched_frames.get(run.frames[index].forecast_time),
                    )
                )
                for index in range(len(run.frames))
            ]
            for task in asyncio.as_completed(tasks):
                result = await task
                self._apply_result(run, result)
                self._persist_run(run, run_directory)

            self._finalize_run(run)
            self._persist_run(run, run_directory)
        except (ImgwClientError, LatestFrameNotFoundError, OSError, ValueError) as error:
            run.status = ForecastRunStatus.FAILED
            run.error = str(error)
            self._persist_run(run, run_directory)
            LOGGER.error("run=%s event=run_failed error=%s", run.run_id, error)
        except Exception as error:
            run.status = ForecastRunStatus.FAILED
            run.error = f"Unexpected ingestion failure: {error}"
            self._persist_run(run, run_directory)
            LOGGER.exception("run=%s event=run_failed unexpected=true", run.run_id)
            raise

        return run

    async def _download_frame(
        self,
        frame: ForecastFrame,
        run_directory: Path,
        prefetched_frame: DownloadedFrame | None,
    ) -> FrameDownloadResult:
        try:
            downloaded = prefetched_frame or await self.client.fetch_frame(frame.forecast_time)
            await self.client.save_frame(downloaded, run_directory / frame.local_filename)
            return FrameDownloadResult(
                frame_index=frame.frame_index,
                status=FrameValidationStatus.VALID,
                downloaded_frame=downloaded,
            )
        except FrameUnavailableError as error:
            status = (
                FrameValidationStatus.MISSING
                if error.status_code == 404
                else FrameValidationStatus.FAILED
            )
            return FrameDownloadResult(
                frame_index=frame.frame_index,
                status=status,
                error=str(error),
            )
        except (ImgwClientError, OSError) as error:
            return FrameDownloadResult(
                frame_index=frame.frame_index,
                status=FrameValidationStatus.FAILED,
                error=str(error),
            )

    @staticmethod
    def _apply_result(run: ForecastRun, result: FrameDownloadResult) -> None:
        frame = run.frames[result.frame_index]
        frame.validation_status = result.status
        frame.error = result.error
        if result.downloaded_frame is not None:
            metadata = result.downloaded_frame.metadata
            frame.width = metadata.width
            frame.height = metadata.height
            frame.size_bytes = metadata.size_bytes
            frame.sha256 = hashlib.sha256(result.downloaded_frame.content).hexdigest()

        run.downloaded_frames = sum(
            item.validation_status == FrameValidationStatus.VALID for item in run.frames
        )
        run.coverage = run.downloaded_frames / run.expected_frames

    def _finalize_run(self, run: ForecastRun) -> None:
        unavailable_frames = [
            frame
            for frame in run.frames
            if frame.validation_status != FrameValidationStatus.VALID
        ]
        failed_frames = [
            frame
            for frame in unavailable_frames
            if frame.validation_status == FrameValidationStatus.FAILED
        ]
        run.missing_timestamps = [frame.forecast_time for frame in unavailable_frames]

        if failed_frames:
            failed_times = ", ".join(format_utc_iso(frame.forecast_time) for frame in failed_frames)
            run.status = ForecastRunStatus.FAILED
            run.error = f"Frame retrieval or persistence failed: {failed_times}"
        elif unavailable_frames and not self.allow_missing_frames:
            missing_times = ", ".join(
                format_utc_iso(frame.forecast_time) for frame in unavailable_frames
            )
            run.status = ForecastRunStatus.FAILED
            run.error = f"Missing required frames: {missing_times}"
        elif run.coverage < self.minimum_frame_coverage:
            run.status = ForecastRunStatus.FAILED
            run.error = (
                f"Frame coverage {run.coverage:.3f} is below required "
                f"{self.minimum_frame_coverage:.3f}"
            )
        else:
            run.status = ForecastRunStatus.COMPLETED
            run.error = None

        LOGGER.info(
            "run=%s event=run_%s frames=%d expected=%d coverage=%.3f",
            run.run_id,
            run.status.value,
            run.downloaded_frames,
            run.expected_frames,
            run.coverage,
        )

    def _persist_run(self, run: ForecastRun, run_directory: Path) -> None:
        run.updated_at = datetime.now(UTC)
        if self.repository is not None:
            self.repository.upsert_run(run)
        write_forecast_manifest(run, run_directory)
