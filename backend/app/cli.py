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
from app.imgw_client import ImgwClientError, ImgwMergeClient


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


def default_probe_timestamp() -> datetime:
    now = datetime.now(UTC)
    return now.replace(minute=now.minute - now.minute % 10, second=0, microsecond=0)


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
        help="source timestamp as timezone-aware ISO 8601; defaults to current UTC 10-minute slot",
    )
    check_parser.add_argument(
        "--save",
        type=Path,
        help="optionally save the validated JPEG atomically to this path",
    )
    return parser


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


async def check_imgw(timestamp: datetime, save_path: Path | None, settings: Settings) -> None:
    async with create_client(settings) as client:
        if save_path is None:
            frame = await client.fetch_frame(timestamp)
            metadata = frame.metadata
        else:
            metadata = await client.download_frame(timestamp, save_path)

    result = {
        "status": "ok",
        "forecast_time": metadata.forecast_time.isoformat(),
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
    )

    if arguments.command == "check-imgw":
        timestamp = arguments.timestamp or default_probe_timestamp()
        try:
            asyncio.run(check_imgw(timestamp, arguments.save, settings))
        except (ImgwClientError, OSError, ValueError) as error:
            print(f"check-imgw failed: {error}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())

