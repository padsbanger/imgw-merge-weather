"""Safe FFmpeg video rendering and ffprobe artifact validation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.database import ForecastRepository, VideoRepository
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)

LOGGER = logging.getLogger(__name__)


class VideoGenerationError(RuntimeError):
    """Base error for a rejected or failed video generation."""


class VideoPrerequisiteError(VideoGenerationError):
    """Raised before rendering when a run or its frames cannot be encoded safely."""


class VideoEncodingError(VideoGenerationError):
    """Raised when FFmpeg does not produce an output."""


class VideoValidationError(VideoGenerationError):
    """Raised when ffprobe rejects an encoded artifact."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], float], Awaitable[CommandResult]]


async def run_command(arguments: Sequence[str], timeout_seconds: float) -> CommandResult:
    """Run one fixed-argument subprocess without a shell and bound its execution time."""

    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except TimeoutError as error:
        process.kill()
        await process.communicate()
        raise VideoEncodingError(
            f"Command timed out after {timeout_seconds:g} seconds"
        ) from error
    except asyncio.CancelledError:
        process.terminate()
        await process.communicate()
        raise
    return CommandResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def resolve_video_output_path(output_directory: Path, filename: str) -> Path:
    """Resolve a server-created MP4 basename inside the configured output directory."""

    output_root = output_directory.resolve()
    output_path = (output_root / filename).resolve()
    if output_path.parent != output_root or output_path.suffix.lower() != ".mp4":
        raise VideoPrerequisiteError("Video output path is outside the output directory")
    return output_path


class VideoGenerationService:
    """Create and render independently persisted video artifacts from forecast runs."""

    def __init__(
        self,
        *,
        settings: Settings,
        forecast_repository: ForecastRepository,
        video_repository: VideoRepository,
        command_runner: CommandRunner = run_command,
    ) -> None:
        self.settings = settings
        self.forecast_repository = forecast_repository
        self.video_repository = video_repository
        self.command_runner = command_runner

    def create_generation(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        fps: int | None = None,
        created_at: datetime | None = None,
    ) -> VideoGeneration:
        run = self.forecast_repository.get_run(run_id)
        if run is None:
            raise VideoPrerequisiteError("Forecast run not found")
        effective_fps = fps if fps is not None else self.settings.video_fps
        if not 1 <= effective_fps <= 30:
            raise VideoPrerequisiteError("Video FPS must be between 1 and 30")
        self._validated_frame_paths(run)
        if run.resolved_start_time is None or run.forecast_end_time is None:
            raise VideoPrerequisiteError("Forecast run does not have a resolved time range")

        timestamp = created_at or datetime.now(UTC)
        video_id = f"video_{uuid.uuid4().hex}"
        mode_label = "source" if mode == VideoMode.SOURCE else "square"
        filename = (
            f"merge_{run.resolved_start_time:%Y-%m-%d_%H-%M}_to_"
            f"{run.forecast_end_time:%H-%M}_{mode_label}_{video_id[-8:]}.mp4"
        )
        video = VideoGeneration(
            video_id=video_id,
            run_id=run.run_id,
            created_at=timestamp,
            updated_at=timestamp,
            mode=mode,
            fps=effective_fps,
            codec=self.settings.video_codec,
            crf=self.settings.video_crf,
            preset=self.settings.video_preset,
            output_filename=filename,
        )
        self.video_repository.upsert(video)
        LOGGER.info(
            "video=%s run=%s event=video_pending mode=%s fps=%d",
            video.video_id,
            video.run_id,
            video.mode.value,
            video.fps,
        )
        return video

    async def generate(self, video_id: str) -> VideoGeneration:
        video = self.video_repository.get(video_id)
        if video is None:
            raise VideoPrerequisiteError("Video generation not found")
        run = self.forecast_repository.get_run(video.run_id)
        if run is None:
            return self._fail(video, "Forecast run no longer exists")

        output_path = resolve_video_output_path(
            self.settings.output_dir, video.output_filename
        )
        temporary_output = resolve_video_output_path(
            self.settings.output_dir, f".{video.video_id}.tmp.mp4"
        )
        video.status = VideoGenerationStatus.RENDERING
        video.updated_at = datetime.now(UTC)
        video.error = None
        self.video_repository.upsert(video)
        LOGGER.info("video=%s run=%s event=ffmpeg_start", video.video_id, video.run_id)

        try:
            frame_paths = self._validated_frame_paths(run)
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
            temporary_output.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f".{video.video_id}.frames.", dir=self.settings.output_dir
            ) as staging_name:
                staging_directory = Path(staging_name)
                for position, frame_path in enumerate(frame_paths):
                    (staging_directory / f"frame_{position:06d}.jpg").symlink_to(frame_path)
                ffmpeg_result = await self.command_runner(
                    self._ffmpeg_arguments(video, staging_directory, temporary_output),
                    self.settings.video_timeout_seconds,
                )
            if ffmpeg_result.returncode != 0:
                detail = ffmpeg_result.stderr.strip()[-2_000:] or "no FFmpeg error output"
                raise VideoEncodingError(f"FFmpeg failed: {detail}")
            metadata = await self._probe_and_validate(video, run, temporary_output)
            os.replace(temporary_output, output_path)
        except asyncio.CancelledError:
            temporary_output.unlink(missing_ok=True)
            self._fail(video, "Video generation cancelled during application shutdown")
            raise
        except (OSError, ValueError, VideoGenerationError) as error:
            temporary_output.unlink(missing_ok=True)
            return self._fail(video, str(error) or "Video generation failed")
        except Exception as error:  # defensive boundary for background task persistence
            temporary_output.unlink(missing_ok=True)
            LOGGER.exception(
                "video=%s run=%s event=video_failed unexpected=true",
                video.video_id,
                video.run_id,
            )
            return self._fail(video, str(error) or "Unexpected video generation failure")

        video.status = VideoGenerationStatus.COMPLETED
        video.updated_at = datetime.now(UTC)
        video.width = metadata.width
        video.height = metadata.height
        video.duration_seconds = metadata.duration_seconds
        video.size_bytes = metadata.size_bytes
        video.error = None
        self.video_repository.upsert(video)
        LOGGER.info(
            "video=%s run=%s event=video_completed size_bytes=%d duration_seconds=%.3f",
            video.video_id,
            video.run_id,
            metadata.size_bytes,
            metadata.duration_seconds,
        )
        return video

    def _validated_frame_paths(self, run: ForecastRun) -> list[Path]:
        if run.status != ForecastRunStatus.COMPLETED:
            raise VideoPrerequisiteError("Only completed forecast runs can generate videos")
        valid_frames = sorted(
            (
                frame
                for frame in run.frames
                if frame.validation_status == FrameValidationStatus.VALID
            ),
            key=lambda frame: frame.forecast_time,
        )
        if not valid_frames:
            raise VideoPrerequisiteError("Forecast run has no valid frames")
        unavailable = [
            frame.forecast_time
            for frame in run.frames
            if frame.validation_status != FrameValidationStatus.VALID
        ]
        if unavailable and not run.allow_missing_frames:
            missing = ", ".join(timestamp.isoformat() for timestamp in unavailable)
            raise VideoPrerequisiteError(f"Required forecast frames are unavailable: {missing}")
        if unavailable and run.coverage < run.minimum_frame_coverage:
            raise VideoPrerequisiteError(
                f"Forecast frame coverage {run.coverage:.3f} is below required "
                f"{run.minimum_frame_coverage:.3f}"
            )

        dimensions = {(frame.width, frame.height) for frame in valid_frames}
        if None in {value for pair in dimensions for value in pair} or len(dimensions) != 1:
            raise VideoPrerequisiteError(
                "All video frames must have known, consistent dimensions"
            )

        runs_root = self.settings.runs_dir.resolve()
        run_directory = (runs_root / run.run_id).resolve()
        frames_directory = (run_directory / "frames").resolve()
        if run_directory.parent != runs_root:
            raise VideoPrerequisiteError("Forecast run path is outside the runs directory")

        paths: list[Path] = []
        for frame in valid_frames:
            path = (run_directory / frame.local_filename).resolve()
            if not path.is_relative_to(frames_directory) or not path.is_file():
                raise VideoPrerequisiteError(
                    f"Validated frame file is unavailable for index {frame.frame_index}"
                )
            paths.append(path)
        return paths

    def _ffmpeg_arguments(
        self,
        video: VideoGeneration,
        staging_directory: Path,
        output_path: Path,
    ) -> list[str]:
        if video.mode == VideoMode.SQUARE:
            size = self.settings.square_video_size
            video_filter = (
                f"scale={size}:{size}:force_original_aspect_ratio=decrease:"
                "in_range=pc:out_range=tv,"
                f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black,"
                "format=yuv420p,setsar=1"
            )
        else:
            video_filter = (
                "scale=iw:ih:in_range=pc:out_range=tv,"
                "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p,setsar=1"
            )
        return [
            self.settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-framerate",
            str(video.fps),
            "-start_number",
            "0",
            "-i",
            str(staging_directory / "frame_%06d.jpg"),
            "-vf",
            video_filter,
            "-c:v",
            video.codec,
            "-preset",
            video.preset,
            "-crf",
            str(video.crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            "-f",
            "mp4",
            str(output_path),
        ]

    async def _probe_and_validate(
        self,
        video: VideoGeneration,
        run: ForecastRun,
        output_path: Path,
    ) -> VideoMetadata:
        if not output_path.is_file():
            raise VideoValidationError("FFmpeg did not create an output file")
        size_bytes = output_path.stat().st_size
        if size_bytes < self.settings.min_video_bytes:
            raise VideoValidationError(
                f"Video output is suspiciously small ({size_bytes} bytes)"
            )
        probe = await self.command_runner(
            [
                self.settings.ffprobe_binary,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output_path),
            ],
            min(self.settings.video_timeout_seconds, 60),
        )
        if probe.returncode != 0:
            detail = probe.stderr.strip()[-2_000:] or "no ffprobe error output"
            raise VideoValidationError(f"ffprobe failed: {detail}")
        try:
            payload = json.loads(probe.stdout)
            stream = next(
                item for item in payload.get("streams", []) if item.get("codec_type") == "video"
            )
            width = int(stream["width"])
            height = int(stream["height"])
            duration = float(stream.get("duration") or payload["format"]["duration"])
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
            raise VideoValidationError("ffprobe returned incomplete video metadata") from error

        first_frame = next(
            frame
            for frame in run.frames
            if frame.validation_status == FrameValidationStatus.VALID
        )
        if video.mode == VideoMode.SQUARE:
            expected_width = expected_height = self.settings.square_video_size
        else:
            if first_frame.width is None or first_frame.height is None:
                raise VideoValidationError("Source frame dimensions are unavailable")
            expected_width = first_frame.width + first_frame.width % 2
            expected_height = first_frame.height + first_frame.height % 2
        if stream.get("codec_name") != "h264":
            raise VideoValidationError("Video codec is not H.264")
        if stream.get("pix_fmt") != "yuv420p":
            raise VideoValidationError("Video pixel format is not yuv420p")
        if (width, height) != (expected_width, expected_height):
            raise VideoValidationError(
                f"Video dimensions are {width}x{height}, expected "
                f"{expected_width}x{expected_height}"
            )
        if duration <= 0:
            raise VideoValidationError("Video duration must be greater than zero")
        return VideoMetadata(
            width=width,
            height=height,
            duration_seconds=duration,
            size_bytes=size_bytes,
        )

    def _fail(self, video: VideoGeneration, error: str) -> VideoGeneration:
        video.status = VideoGenerationStatus.FAILED
        video.updated_at = datetime.now(UTC)
        video.error = error
        self.video_repository.upsert(video)
        LOGGER.error(
            "video=%s run=%s event=video_failed error=%s",
            video.video_id,
            video.run_id,
            error,
        )
        return video


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    width: int
    height: int
    duration_seconds: float
    size_bytes: int
