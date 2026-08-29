from datetime import UTC, datetime, timedelta

import pytest

from app.freshness import FreshnessState, calculate_forecast_freshness
from app.models import ForecastRun

START = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def make_run() -> ForecastRun:
    return ForecastRun(
        run_id="merge_freshness",
        discovered_at=START,
        updated_at=START,
        requested_start_time=START,
        resolved_start_time=START,
        forecast_end_time=START + timedelta(hours=8),
        interval_minutes=10,
        forecast_hours=8,
        allow_missing_frames=False,
        minimum_frame_coverage=0.9,
    )


@pytest.mark.parametrize(
    ("age_seconds", "expected_state"),
    [
        (0, FreshnessState.FRESH),
        (899, FreshnessState.FRESH),
        (900, FreshnessState.DELAYED),
        (1800, FreshnessState.DELAYED),
        (1801, FreshnessState.STALE),
    ],
)
def test_freshness_thresholds(age_seconds: int, expected_state: FreshnessState) -> None:
    freshness = calculate_forecast_freshness(
        make_run(),
        now=START + timedelta(seconds=age_seconds),
    )

    assert freshness.state == expected_state
    assert freshness.reference_time == START
    assert freshness.age_seconds == age_seconds


def test_future_reference_time_never_reports_negative_age() -> None:
    freshness = calculate_forecast_freshness(make_run(), now=START - timedelta(minutes=5))

    assert freshness.state == FreshnessState.FRESH
    assert freshness.age_seconds == 0
