"""Canonical time handling and forecast-sequence construction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.imgw_client import DownloadedFrame

LOGGER = logging.getLogger(__name__)

WARSAW_TIMEZONE_NAME = "Europe/Warsaw"
WARSAW_TIMEZONE = ZoneInfo(WARSAW_TIMEZONE_NAME)
DEFAULT_FRAME_INTERVAL_MINUTES = 10
DEFAULT_FORECAST_HOURS = 8
DEFAULT_MAX_START_FALLBACK_STEPS = 6


class ForecastTimeError(ValueError):
    """Invalid forecast time or sequence configuration."""


class LatestFrameNotFoundError(RuntimeError):
    """No valid starting frame was found within the fallback window."""

    def __init__(self, attempted_times: tuple[datetime, ...]) -> None:
        attempted = ", ".join(timestamp.isoformat() for timestamp in attempted_times)
        super().__init__(f"No IMGW MERGE start frame found; attempted UTC times: {attempted}")
        self.attempted_times = attempted_times


class FrameFetcher(Protocol):
    async def fetch_frame(self, timestamp: datetime) -> DownloadedFrame: ...


@dataclass(frozen=True, slots=True)
class LatestFrameProbe:
    expected_start_time: datetime
    resolved_start_time: datetime
    fallback_steps: int
    attempted_times: tuple[datetime, ...]
    frame: DownloadedFrame


@dataclass(frozen=True, slots=True)
class CompleteSequenceProbe:
    expected_start_time: datetime
    resolved_start_time: datetime
    fallback_steps: int
    attempted_start_times: tuple[datetime, ...]
    prefetched_frames: dict[datetime, DownloadedFrame]


def require_aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ForecastTimeError("Forecast timestamps must be timezone-aware")


def to_utc(timestamp: datetime) -> datetime:
    """Convert an aware timestamp to the canonical UTC representation."""

    require_aware(timestamp)
    return timestamp.astimezone(UTC)


def to_warsaw(timestamp: datetime) -> datetime:
    """Convert an aware timestamp for Europe/Warsaw display."""

    return to_utc(timestamp).astimezone(WARSAW_TIMEZONE)


def format_warsaw_time(timestamp: datetime) -> str:
    return to_warsaw(timestamp).strftime("%d.%m.%Y %H:%M")


def format_utc_iso(timestamp: datetime) -> str:
    return to_utc(timestamp).isoformat().replace("+00:00", "Z")


def floor_to_interval(
    timestamp: datetime,
    interval_minutes: int = DEFAULT_FRAME_INTERVAL_MINUTES,
) -> datetime:
    """Floor an aware instant to an interval boundary and return canonical UTC."""

    require_aware(timestamp)
    if interval_minutes <= 0:
        raise ForecastTimeError("Frame interval must be greater than zero")

    interval_seconds = interval_minutes * 60
    floored_seconds = int(timestamp.timestamp()) // interval_seconds * interval_seconds
    return datetime.fromtimestamp(floored_seconds, tz=UTC)


def build_frame_times(
    start_time: datetime,
    *,
    horizon_hours: int = DEFAULT_FORECAST_HOURS,
    interval_minutes: int = DEFAULT_FRAME_INTERVAL_MINUTES,
) -> list[datetime]:
    """Build an inclusive, ordered forecast sequence in canonical UTC."""

    start_utc = to_utc(start_time)
    if horizon_hours <= 0:
        raise ForecastTimeError("Forecast horizon must be greater than zero")
    if interval_minutes <= 0:
        raise ForecastTimeError("Frame interval must be greater than zero")

    interval = timedelta(minutes=interval_minutes)
    horizon = timedelta(hours=horizon_hours)
    steps = horizon // interval
    return [start_utc + index * interval for index in range(steps + 1)]


async def probe_latest_available_frame(
    client: FrameFetcher,
    *,
    now: datetime,
    interval_minutes: int = DEFAULT_FRAME_INTERVAL_MINUTES,
    max_fallback_steps: int = DEFAULT_MAX_START_FALLBACK_STEPS,
) -> LatestFrameProbe:
    """Find the newest valid start frame, falling back only on HTTP 404.

    Transient transport failures and invalid response bodies are deliberately surfaced.
    Falling back in those cases could disguise an IMGW outage as an older forecast.
    """

    from app.imgw_client import FrameUnavailableError

    if max_fallback_steps < 0:
        raise ForecastTimeError("Maximum fallback steps must not be negative")

    expected_start = floor_to_interval(now, interval_minutes)
    attempted_times: list[datetime] = []

    for fallback_steps in range(max_fallback_steps + 1):
        candidate = expected_start - timedelta(minutes=interval_minutes * fallback_steps)
        attempted_times.append(candidate)
        try:
            frame = await client.fetch_frame(candidate)
        except FrameUnavailableError as error:
            if error.status_code != 404:
                raise
            LOGGER.info(
                "event=start_probe forecast_time=%s status=unavailable fallback_step=%d",
                candidate.isoformat(),
                fallback_steps,
            )
            continue

        LOGGER.info(
            "event=start_probe forecast_time=%s status=success fallback_step=%d",
            candidate.isoformat(),
            fallback_steps,
        )
        return LatestFrameProbe(
            expected_start_time=expected_start,
            resolved_start_time=candidate,
            fallback_steps=fallback_steps,
            attempted_times=tuple(attempted_times),
            frame=frame,
        )

    raise LatestFrameNotFoundError(tuple(attempted_times))


async def probe_latest_complete_sequence(
    client: FrameFetcher,
    *,
    now: datetime,
    horizon_hours: int = DEFAULT_FORECAST_HOURS,
    interval_minutes: int = DEFAULT_FRAME_INTERVAL_MINUTES,
    max_fallback_steps: int = DEFAULT_MAX_START_FALLBACK_STEPS,
) -> CompleteSequenceProbe:
    """Find the newest start whose first and final forecast frames are published.

    Successful boundary probes are retained for the selected run so ingestion does not
    request those frames twice. Only HTTP 404 advances fallback; intermediate timestamps
    are never shifted and remain subject to the run's missing-frame policy.
    """

    from app.imgw_client import FrameUnavailableError

    if horizon_hours <= 0:
        raise ForecastTimeError("Forecast horizon must be greater than zero")
    if max_fallback_steps < 0:
        raise ForecastTimeError("Maximum fallback steps must not be negative")

    expected_start = floor_to_interval(now, interval_minutes)
    attempted_starts: list[datetime] = []
    prefetched_frames: dict[datetime, DownloadedFrame] = {}

    for fallback_steps in range(max_fallback_steps + 1):
        candidate_start = expected_start - timedelta(
            minutes=interval_minutes * fallback_steps
        )
        candidate_end = candidate_start + timedelta(hours=horizon_hours)
        attempted_starts.append(candidate_start)

        try:
            if candidate_start not in prefetched_frames:
                prefetched_frames[candidate_start] = await client.fetch_frame(candidate_start)
            if candidate_end not in prefetched_frames:
                prefetched_frames[candidate_end] = await client.fetch_frame(candidate_end)
        except FrameUnavailableError as error:
            if error.status_code != 404:
                raise
            LOGGER.info(
                "event=complete_start_probe start_time=%s end_time=%s "
                "status=unavailable fallback_step=%d",
                candidate_start.isoformat(),
                candidate_end.isoformat(),
                fallback_steps,
            )
            continue

        selected_times = set(
            build_frame_times(
                candidate_start,
                horizon_hours=horizon_hours,
                interval_minutes=interval_minutes,
            )
        )
        selected_prefetch = {
            timestamp: frame
            for timestamp, frame in prefetched_frames.items()
            if timestamp in selected_times
        }
        LOGGER.info(
            "event=complete_start_probe start_time=%s end_time=%s "
            "status=success fallback_step=%d",
            candidate_start.isoformat(),
            candidate_end.isoformat(),
            fallback_steps,
        )
        return CompleteSequenceProbe(
            expected_start_time=expected_start,
            resolved_start_time=candidate_start,
            fallback_steps=fallback_steps,
            attempted_start_times=tuple(attempted_starts),
            prefetched_frames=selected_prefetch,
        )

    raise LatestFrameNotFoundError(tuple(attempted_starts))
