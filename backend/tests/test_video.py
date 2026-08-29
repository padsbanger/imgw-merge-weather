from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.config import Settings
from app.database import Database, ForecastRepository, VideoRepository
from app.models import (
    ForecastFrame,
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
    VideoGenerationStatus,
    VideoMode,
)
from app.video import (
    CommandResult,
    VideoGenerationService,
    VideoPrerequisiteError,
)

START = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


class FakeCommands:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        codec: str = "h264",
        pixel_format: str = "yuv420p",
    ) -> None:
        self.width = width
        self.height = height
        self.codec = codec
        self.pixel_format = pixel_format
        self.calls: list[list[str]] = []
        self.staged_targets: list[Path] = []
        self.staged_symlinks: list[bool] = []
        self.overlay_sample: tuple[int, int, int] | None = None

    async def __call__(self, arguments: Any, _timeout: float) -> CommandResult:
        command = list(arguments)
        self.calls.append(command)
        if command[0] == "ffmpeg":
            input_pattern = Path(command[command.index("-i") + 1])
            staged = sorted(input_pattern.parent.glob("frame_*.jpg"))
            self.staged_symlinks = [path.is_symlink() for path in staged]
            self.staged_targets = [path.resolve() for path in staged]
            if staged and not staged[0].is_symlink():
                with Image.open(staged[0]) as image:
                    self.overlay_sample = image.convert("RGB").getpixel(
                        (30, image.height - 30)
                    )
            Path(command[-1]).write_bytes(b"mp4" * 700)
            return CommandResult(0, "", "")
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": self.codec,
                    "pix_fmt": self.pixel_format,
                    "width": self.width,
                    "height": self.height,
                    "duration": "0.600000",
                }
            ],
            "format": {"duration": "0.600000"},
        }
        return CommandResult(0, json.dumps(payload), "")


def make_run(
    settings: Settings,
    *,
    run_id: str = "merge_video_source",
    missing_indices: set[int] | None = None,
    allow_missing: bool = False,
    local_filename: str | None = None,
) -> ForecastRun:
    missing_indices = missing_indices or set()
    frames: list[ForecastFrame] = []
    for index in range(3):
        valid = index not in missing_indices
        filename = (
            local_filename
            if index == 0 and local_filename
            else f"frames/frame_{index:03d}.jpg"
        )
        frames.append(
            ForecastFrame(
                frame_index=index,
                forecast_time=START + timedelta(minutes=10 * index),
                source_url=f"https://cmm.imgw.pl/frame-{index}.jpg",
                local_filename=filename,
                width=1700 if valid else None,
                height=1600 if valid else None,
                size_bytes=2_000 if valid else None,
                sha256=str(index) * 64 if valid else None,
                validation_status=(
                    FrameValidationStatus.VALID if valid else FrameValidationStatus.MISSING
                ),
                error=None if valid else "HTTP 404",
            )
        )
        if valid and local_filename is None:
            frame_path = settings.runs_dir / run_id / filename
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            frame_path.write_bytes(b"jpeg")
    valid_count = 3 - len(missing_indices)
    return ForecastRun(
        run_id=run_id,
        discovered_at=START,
        updated_at=START,
        requested_start_time=START,
        resolved_start_time=START,
        forecast_end_time=START + timedelta(minutes=20),
        interval_minutes=10,
        forecast_hours=8,
        expected_frames=3,
        downloaded_frames=valid_count,
        coverage=valid_count / 3,
        allow_missing_frames=allow_missing,
        minimum_frame_coverage=0.5,
        status=ForecastRunStatus.COMPLETED,
        missing_timestamps=[frames[index].forecast_time for index in sorted(missing_indices)],
        frames=frames,
    )


def make_service(
    tmp_path: Path,
    run: ForecastRun,
    commands: FakeCommands,
) -> tuple[VideoGenerationService, VideoRepository]:
    settings = Settings(data_dir=tmp_path)
    settings.ensure_data_directories()
    database = Database(settings.database_path)
    database.initialize()
    forecast_repository = ForecastRepository(database)
    forecast_repository.upsert_run(run)
    video_repository = VideoRepository(database)
    service = VideoGenerationService(
        settings=settings,
        forecast_repository=forecast_repository,
        video_repository=video_repository,
        command_runner=commands,
    )
    return service, video_repository


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "probe_size", "filter_fragment"),
    [
        (VideoMode.SOURCE, (1700, 1600), "pad=ceil(iw/2)*2"),
        (VideoMode.SQUARE, (1080, 1080), "force_original_aspect_ratio=decrease"),
    ],
)
async def test_generates_and_validates_browser_compatible_mp4(
    tmp_path: Path,
    mode: VideoMode,
    probe_size: tuple[int, int],
    filter_fragment: str,
) -> None:
    settings = Settings(data_dir=tmp_path)
    run = make_run(settings)
    commands = FakeCommands(width=probe_size[0], height=probe_size[1])
    service, repository = make_service(tmp_path, run, commands)

    pending = service.create_generation(run_id=run.run_id, mode=mode)
    result = await service.generate(pending.video_id)

    assert result.status == VideoGenerationStatus.COMPLETED
    assert (result.width, result.height) == probe_size
    assert result.duration_seconds == 0.6
    assert result.size_bytes == 2_100
    assert repository.get(result.video_id) == result
    output_path = settings.output_dir / result.output_filename
    assert output_path.read_bytes() == b"mp4" * 700
    assert not (settings.output_dir / f".{result.video_id}.tmp.mp4").exists()
    ffmpeg = commands.calls[0]
    assert ffmpeg[0] == "ffmpeg"
    assert ffmpeg[ffmpeg.index("-c:v") + 1] == "libx264"
    assert ffmpeg[ffmpeg.index("-pix_fmt") + 1] == "yuv420p"
    assert filter_fragment in ffmpeg[ffmpeg.index("-vf") + 1]
    assert "in_range=pc:out_range=tv" in ffmpeg[ffmpeg.index("-vf") + 1]


@pytest.mark.asyncio
async def test_permissive_video_skips_missing_frames_without_duplication(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    run = make_run(settings, missing_indices={1}, allow_missing=True)
    commands = FakeCommands(width=1700, height=1600)
    service, _ = make_service(tmp_path, run, commands)

    video = service.create_generation(run_id=run.run_id, mode=VideoMode.SOURCE)
    result = await service.generate(video.video_id)

    assert result.status == VideoGenerationStatus.COMPLETED
    assert commands.staged_targets == [
        (settings.runs_dir / run.run_id / "frames/frame_000.jpg").resolve(),
        (settings.runs_dir / run.run_id / "frames/frame_002.jpg").resolve(),
    ]


@pytest.mark.asyncio
async def test_selected_range_and_timestamp_overlay_are_persisted_and_staged(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    run = make_run(settings)
    for frame in run.frames:
        path = settings.runs_dir / run.run_id / frame.local_filename
        Image.new("RGB", (1700, 1600), (80, 120, 160)).save(path, format="JPEG")
    commands = FakeCommands(width=1700, height=1600)
    service, _ = make_service(tmp_path, run, commands)

    video = service.create_generation(
        run_id=run.run_id,
        mode=VideoMode.SOURCE,
        start_frame_index=1,
        end_frame_index=2,
        timestamp_overlay=True,
    )
    result = await service.generate(video.video_id)

    assert result.status == VideoGenerationStatus.COMPLETED
    assert result.start_frame_index == 1
    assert result.end_frame_index == 2
    assert result.timestamp_overlay is True
    assert commands.staged_symlinks == [False, False]
    assert commands.overlay_sample is not None
    assert commands.overlay_sample != (80, 120, 160)


def test_rejects_invalid_video_frame_range(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    run = make_run(settings)
    service, _ = make_service(
        tmp_path, run, FakeCommands(width=1700, height=1600)
    )

    with pytest.raises(VideoPrerequisiteError, match="start must not be after"):
        service.create_generation(
            run_id=run.run_id,
            mode=VideoMode.SOURCE,
            start_frame_index=2,
            end_frame_index=1,
        )
    with pytest.raises(VideoPrerequisiteError, match="between 0 and 2"):
        service.create_generation(
            run_id=run.run_id,
            mode=VideoMode.SOURCE,
            start_frame_index=0,
            end_frame_index=3,
        )


def test_rejects_incomplete_failed_or_unsafe_forecast_sources(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    strict_missing = make_run(settings, missing_indices={1}, allow_missing=False)
    commands = FakeCommands(width=1700, height=1600)
    service, repository = make_service(tmp_path, strict_missing, commands)

    with pytest.raises(VideoPrerequisiteError, match="Required forecast frames"):
        service.create_generation(run_id=strict_missing.run_id, mode=VideoMode.SOURCE)
    assert repository.list() == []

    unsafe = make_run(
        settings,
        run_id="merge_video_unsafe",
        local_filename="../outside.jpg",
    )
    (settings.runs_dir / unsafe.run_id / "outside.jpg").parent.mkdir(
        parents=True, exist_ok=True
    )
    (settings.runs_dir / unsafe.run_id / "outside.jpg").write_bytes(b"jpeg")
    unsafe_service, _ = make_service(tmp_path, unsafe, commands)
    with pytest.raises(VideoPrerequisiteError, match="unavailable for index 0"):
        unsafe_service.create_generation(run_id=unsafe.run_id, mode=VideoMode.SOURCE)

    failed = make_run(settings, run_id="merge_video_failed")
    failed.status = ForecastRunStatus.FAILED
    failed_service, _ = make_service(tmp_path, failed, commands)
    with pytest.raises(VideoPrerequisiteError, match="Only completed"):
        failed_service.create_generation(run_id=failed.run_id, mode=VideoMode.SOURCE)


@pytest.mark.asyncio
async def test_failed_ffprobe_never_publishes_or_completes_video(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    run = make_run(settings)
    commands = FakeCommands(width=1700, height=1600, codec="vp9")
    service, repository = make_service(tmp_path, run, commands)

    video = service.create_generation(run_id=run.run_id, mode=VideoMode.SOURCE)
    result = await service.generate(video.video_id)

    assert result.status == VideoGenerationStatus.FAILED
    assert result.error == "Video codec is not H.264"
    assert not (settings.output_dir / result.output_filename).exists()
    assert repository.get(result.video_id) == result
