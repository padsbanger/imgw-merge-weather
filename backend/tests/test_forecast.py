from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

import pytest

from app.forecast import (
    ForecastTimeError,
    LatestFrameNotFoundError,
    build_frame_times,
    floor_to_interval,
    format_utc_iso,
    format_warsaw_time,
    probe_latest_available_frame,
    probe_latest_complete_sequence,
    to_utc,
    to_warsaw,
)
from app.imgw_client import (
    DownloadedFrame,
    FrameMetadata,
    FrameUnavailableError,
    build_frame_url,
)

BASE_URL = "https://cmm.imgw.pl/wp-content/uploads/production/MERGE"


def make_frame(timestamp: datetime) -> DownloadedFrame:
    source_url = build_frame_url(BASE_URL, timestamp)
    return DownloadedFrame(
        metadata=FrameMetadata(
            forecast_time=timestamp,
            source_url=source_url,
            content_type="image/jpeg",
            size_bytes=455_000,
            width=1700,
            height=1600,
            image_format="JPEG",
        ),
        content=b"frame",
    )


class StubFrameFetcher:
    def __init__(
        self,
        unavailable_times: set[datetime],
        *,
        unavailable_status: int = 404,
    ) -> None:
        self.unavailable_times = unavailable_times
        self.unavailable_status = unavailable_status
        self.requested_times: list[datetime] = []

    async def fetch_frame(self, timestamp: datetime) -> DownloadedFrame:
        self.requested_times.append(timestamp)
        if timestamp in self.unavailable_times:
            raise FrameUnavailableError(
                build_frame_url(BASE_URL, timestamp),
                self.unavailable_status,
            )
        return make_frame(timestamp)


def test_utc_canonicalization_and_warsaw_summer_display() -> None:
    warsaw_offset = timezone(timedelta(hours=2))
    local_time = datetime(2026, 8, 29, 12, 20, tzinfo=warsaw_offset)

    assert to_utc(local_time) == datetime(2026, 8, 29, 10, 20, tzinfo=UTC)
    assert format_utc_iso(local_time) == "2026-08-29T10:20:00Z"
    assert to_warsaw(to_utc(local_time)).utcoffset() == timedelta(hours=2)
    assert format_warsaw_time(to_utc(local_time)) == "29.08.2026 12:20"


def test_warsaw_display_uses_winter_offset() -> None:
    utc_time = datetime(2026, 12, 15, 10, 20, tzinfo=UTC)

    assert to_warsaw(utc_time).hour == 11
    assert to_warsaw(utc_time).utcoffset() == timedelta(hours=1)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ForecastTimeError, match="timezone-aware"):
        to_utc(datetime(2026, 8, 29, 10, 20))


def test_floor_to_ten_minute_interval_returns_utc() -> None:
    warsaw_offset = timezone(timedelta(hours=2))
    timestamp = datetime(2026, 8, 29, 12, 27, 59, 999_999, tzinfo=warsaw_offset)

    assert floor_to_interval(timestamp) == datetime(2026, 8, 29, 10, 20, tzinfo=UTC)


def test_builds_inclusive_eight_hour_sequence_of_49_frames() -> None:
    start = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)

    frames = build_frame_times(start)

    assert len(frames) == 49
    assert frames[0] == start
    assert frames[-1] == datetime(2026, 8, 29, 18, 20, tzinfo=UTC)
    assert all(
        later - earlier == timedelta(minutes=10)
        for earlier, later in pairwise(frames)
    )
    assert all(timestamp.tzinfo is UTC for timestamp in frames)


def test_builds_two_hour_lookback_plus_eight_hour_forecast_of_61_frames() -> None:
    current_cycle = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)

    frames = build_frame_times(current_cycle, lookback_hours=2)

    assert len(frames) == 61
    assert frames[0] == datetime(2026, 8, 29, 8, 20, tzinfo=UTC)
    assert frames[12] == current_cycle
    assert frames[-1] == datetime(2026, 8, 29, 18, 20, tzinfo=UTC)


def test_sequence_converts_local_start_to_canonical_utc() -> None:
    warsaw_offset = timezone(timedelta(hours=2))
    local_start = datetime(2026, 8, 29, 12, 20, tzinfo=warsaw_offset)

    frames = build_frame_times(local_start, horizon_hours=1, interval_minutes=20)

    assert frames == [
        datetime(2026, 8, 29, 10, 20, tzinfo=UTC),
        datetime(2026, 8, 29, 10, 40, tzinfo=UTC),
        datetime(2026, 8, 29, 11, 0, tzinfo=UTC),
        datetime(2026, 8, 29, 11, 20, tzinfo=UTC),
    ]


@pytest.mark.parametrize(
    ("horizon_hours", "interval_minutes", "message"),
    [
        (0, 10, "horizon"),
        (8, 0, "interval"),
    ],
)
def test_sequence_rejects_invalid_configuration(
    horizon_hours: int,
    interval_minutes: int,
    message: str,
) -> None:
    with pytest.raises(ForecastTimeError, match=message):
        build_frame_times(
            datetime(2026, 8, 29, 10, 20, tzinfo=UTC),
            horizon_hours=horizon_hours,
            interval_minutes=interval_minutes,
        )


def test_sequence_rejects_negative_lookback() -> None:
    with pytest.raises(ForecastTimeError, match="lookback"):
        build_frame_times(
            datetime(2026, 8, 29, 10, 20, tzinfo=UTC),
            lookback_hours=-1,
        )


@pytest.mark.asyncio
async def test_latest_probe_falls_back_on_missing_newest_frames() -> None:
    expected = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)
    first_fallback = datetime(2026, 8, 29, 10, 10, tzinfo=UTC)
    resolved = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    fetcher = StubFrameFetcher({expected, first_fallback})

    probe = await probe_latest_available_frame(
        fetcher,
        now=datetime(2026, 8, 29, 12, 27, tzinfo=timezone(timedelta(hours=2))),
        max_fallback_steps=6,
    )

    assert probe.expected_start_time == expected
    assert probe.resolved_start_time == resolved
    assert probe.fallback_steps == 2
    assert probe.attempted_times == (expected, first_fallback, resolved)
    assert fetcher.requested_times == [expected, first_fallback, resolved]
    assert probe.frame.metadata.forecast_time == resolved


@pytest.mark.asyncio
async def test_latest_probe_reports_every_attempt_when_fallback_is_exhausted() -> None:
    attempted = {
        datetime(2026, 8, 29, 10, 20, tzinfo=UTC),
        datetime(2026, 8, 29, 10, 10, tzinfo=UTC),
        datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
    }
    fetcher = StubFrameFetcher(attempted)

    with pytest.raises(LatestFrameNotFoundError) as error:
        await probe_latest_available_frame(
            fetcher,
            now=datetime(2026, 8, 29, 10, 27, tzinfo=UTC),
            max_fallback_steps=2,
        )

    assert set(error.value.attempted_times) == attempted
    assert fetcher.requested_times == sorted(attempted, reverse=True)


@pytest.mark.asyncio
async def test_latest_probe_does_not_hide_non_404_source_failures() -> None:
    expected = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)
    fetcher = StubFrameFetcher({expected}, unavailable_status=503)

    with pytest.raises(FrameUnavailableError) as error:
        await probe_latest_available_frame(
            fetcher,
            now=datetime(2026, 8, 29, 10, 27, tzinfo=UTC),
        )

    assert error.value.status_code == 503
    assert fetcher.requested_times == [expected]


@pytest.mark.asyncio
async def test_complete_sequence_probe_falls_back_when_latest_endpoint_is_missing() -> None:
    expected_start = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)
    missing_latest_end = datetime(2026, 8, 29, 11, 20, tzinfo=UTC)
    resolved_start = datetime(2026, 8, 29, 10, 10, tzinfo=UTC)
    resolved_end = datetime(2026, 8, 29, 11, 10, tzinfo=UTC)
    fetcher = StubFrameFetcher({missing_latest_end})

    probe = await probe_latest_complete_sequence(
        fetcher,
        now=datetime(2026, 8, 29, 10, 27, tzinfo=UTC),
        horizon_hours=1,
        max_fallback_steps=2,
    )

    assert probe.expected_start_time == expected_start
    assert probe.resolved_start_time == resolved_start
    assert probe.fallback_steps == 1
    assert probe.attempted_start_times == (expected_start, resolved_start)
    assert set(probe.prefetched_frames) == {expected_start, resolved_start, resolved_end}


@pytest.mark.asyncio
async def test_complete_sequence_probe_includes_lookback_boundary() -> None:
    current_cycle = datetime(2026, 8, 29, 10, 20, tzinfo=UTC)
    lookback_start = datetime(2026, 8, 29, 8, 20, tzinfo=UTC)
    forecast_end = datetime(2026, 8, 29, 18, 20, tzinfo=UTC)
    fetcher = StubFrameFetcher(set())

    probe = await probe_latest_complete_sequence(
        fetcher,
        now=datetime(2026, 8, 29, 10, 27, tzinfo=UTC),
        horizon_hours=8,
        lookback_hours=2,
    )

    assert probe.resolved_start_time == current_cycle
    assert set(probe.prefetched_frames) == {
        lookback_start,
        current_cycle,
        forecast_end,
    }
