"""Command-line utilities for operating imgw-merge-weather."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.database import VideoRepository
from app.forecast import (
    LatestFrameNotFoundError,
    format_utc_iso,
    format_warsaw_time,
    probe_latest_available_frame,
)
from app.imgw_client import ImgwClientError, ImgwMergeClient
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)
from app.persistence import initialize_forecast_persistence
from app.services.ingestion import ForecastIngestionService
from app.video import VideoGenerationError, VideoGenerationService


def parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO 8601, for example 2026-08-29T12:50:00Z"
        ) from error

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return timestamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imgw-merge-weather")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check-imgw",
        help="GET and validate one MERGE frame without fetching a forecast run",
    )
    check_parser.add_argument(
        "--timestamp",
        type=parse_timestamp,
        help=(
            "forecast valid time as timezone-aware ISO 8601; "
            "defaults to probing the current UTC 10-minute slot"
        ),
    )
    check_parser.add_argument(
        "--save",
        type=Path,
        help="optionally save the validated JPEG atomically to this path",
    )

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="ingest and persist one complete MERGE forecast run",
    )
    refresh_parser.add_argument(
        "--start",
        type=parse_timestamp,
        help=(
            "explicit forecast start as timezone-aware ISO 8601; "
            "omitting it probes the latest available UTC slot"
        ),
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="generate a validated MP4 from a completed forecast run",
    )
    generate_parser.add_argument("--run", required=True, help="forecast run ID")
    _add_video_arguments(generate_parser)

    generate_latest_parser = subparsers.add_parser(
        "generate-latest",
        help="generate a validated MP4 from the latest completed forecast run",
    )
    _add_video_arguments(generate_latest_parser)
    return parser


def _add_video_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        type=VideoMode,
        choices=list(VideoMode),
        default=VideoMode.SOURCE,
        help="output framing mode",
    )
    parser.add_argument("--fps", type=int, help="frames per second (1-30)")


def create_client(settings: Settings) -> ImgwMergeClient:
    return ImgwMergeClient(
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


async def check_imgw(
    timestamp: datetime | None,
    save_path: Path | None,
    settings: Settings,
) -> None:
    async with create_client(settings) as client:
        if timestamp is None:
            probe = await probe_latest_available_frame(
                client,
                now=datetime.now(UTC),
                interval_minutes=settings.frame_interval_minutes,
                max_fallback_steps=settings.max_start_fallback_steps,
            )
            frame = probe.frame
            fallback_steps = probe.fallback_steps
        else:
            frame = await client.fetch_frame(timestamp)
            fallback_steps = 0

        if save_path is not None:
            await client.save_frame(frame, save_path)

    metadata = frame.metadata

    result = {
        "status": "ok",
        "forecast_time_utc": format_utc_iso(metadata.forecast_time),
        "forecast_time_warsaw": format_warsaw_time(metadata.forecast_time),
        "fallback_steps": fallback_steps,
        "source_url": metadata.source_url,
        "content_type": metadata.content_type,
        "size_bytes": metadata.size_bytes,
        "width": metadata.width,
        "height": metadata.height,
        "image_format": metadata.image_format,
    }
    if save_path is not None:
        result["saved_to"] = str(save_path)
    print(json.dumps(result, indent=2))


async def refresh_forecast(start_time: datetime | None, settings: Settings) -> ForecastRun:
    settings.ensure_data_directories()
    repository, _ = initialize_forecast_persistence(
        database_path=settings.database_path,
        runs_directory=settings.runs_dir,
    )
    async with create_client(settings) as client:
        service = ForecastIngestionService(
            client=client,
            data_dir=settings.data_dir,
            interval_minutes=settings.frame_interval_minutes,
            forecast_hours=settings.forecast_hours,
            max_start_fallback_steps=settings.max_start_fallback_steps,
            allow_missing_frames=settings.allow_missing_frames,
            minimum_frame_coverage=settings.min_frame_coverage,
            repository=repository,
        )
        run = await service.ingest(start_time=start_time)

    result = {
        "run_id": run.run_id,
        "status": run.status.value,
        "requested_start_time": format_utc_iso(run.requested_start_time),
        "resolved_start_time": (
            format_utc_iso(run.resolved_start_time) if run.resolved_start_time else None
        ),
        "forecast_end_time": (
            format_utc_iso(run.forecast_end_time) if run.forecast_end_time else None
        ),
        "expected_frames": run.expected_frames,
        "downloaded_frames": run.downloaded_frames,
        "coverage": run.coverage,
        "missing_timestamps": [format_utc_iso(item) for item in run.missing_timestamps],
        "error": run.error,
        "manifest": f"runs/{run.run_id}/manifest.json",
    }
    print(json.dumps(result, indent=2))
    return run


async def generate_video(
    *,
    run_id: str | None,
    mode: VideoMode,
    fps: int | None,
    settings: Settings,
) -> VideoGeneration:
    settings.ensure_data_directories()
    forecast_repository, _ = initialize_forecast_persistence(
        database_path=settings.database_path,
        runs_directory=settings.runs_dir,
    )
    if run_id is None:
        latest = forecast_repository.get_latest_completed_run()
        if latest is None:
            raise VideoGenerationError("No completed forecast run is available")
        run_id = latest.run_id
    video_repository = VideoRepository(forecast_repository.database)
    service = VideoGenerationService(
        settings=settings,
        forecast_repository=forecast_repository,
        video_repository=video_repository,
    )
    video = service.create_generation(run_id=run_id, mode=mode, fps=fps)
    video = await service.generate(video.video_id)
    print(
        json.dumps(
            {
                "video_id": video.video_id,
                "run_id": video.run_id,
                "status": video.status.value,
                "mode": video.mode.value,
                "fps": video.fps,
                "output": f"output/{video.output_filename}",
                "width": video.width,
                "height": video.height,
                "duration_seconds": video.duration_seconds,
                "size_bytes": video.size_bytes,
                "error": video.error,
            },
            indent=2,
        )
    )
    return video


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )

    if arguments.command == "check-imgw":
        try:
            asyncio.run(check_imgw(arguments.timestamp, arguments.save, settings))
        except (ImgwClientError, LatestFrameNotFoundError, OSError, ValueError) as error:
            print(f"check-imgw failed: {error}", file=sys.stderr)
            return 1
        return 0

    if arguments.command == "refresh":
        try:
            run = asyncio.run(refresh_forecast(arguments.start, settings))
        except (ImgwClientError, LatestFrameNotFoundError, OSError, ValueError) as error:
            print(f"refresh failed: {error}", file=sys.stderr)
            return 1
        return 0 if run.status == ForecastRunStatus.COMPLETED else 1

    if arguments.command in {"generate", "generate-latest"}:
        try:
            video = asyncio.run(
                generate_video(
                    run_id=arguments.run if arguments.command == "generate" else None,
                    mode=arguments.mode,
                    fps=arguments.fps,
                    settings=settings,
                )
            )
        except (OSError, ValueError, VideoGenerationError) as error:
            print(f"video generation failed: {error}", file=sys.stderr)
            return 1
        return 0 if video.status == VideoGenerationStatus.COMPLETED else 1

    parser.error(f"unknown command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
