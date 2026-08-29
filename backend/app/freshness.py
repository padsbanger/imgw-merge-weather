"""Central forecast freshness calculation used by API and future UI consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.forecast import to_utc
from app.models import ForecastRun

FRESH_MAX_AGE_SECONDS = 15 * 60
DELAYED_MAX_AGE_SECONDS = 30 * 60


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class ForecastFreshness:
    state: FreshnessState
    reference_time: datetime
    age_seconds: int


def calculate_forecast_freshness(
    run: ForecastRun,
    *,
    now: datetime | None = None,
) -> ForecastFreshness:
    """Classify age from the run's resolved forecast start, falling back to discovery."""

    current_time = to_utc(now or datetime.now(UTC))
    reference_time = run.resolved_start_time or run.discovered_at
    age_seconds = max(0, int((current_time - reference_time).total_seconds()))
    if age_seconds < FRESH_MAX_AGE_SECONDS:
        state = FreshnessState.FRESH
    elif age_seconds <= DELAYED_MAX_AGE_SECONDS:
        state = FreshnessState.DELAYED
    else:
        state = FreshnessState.STALE
    return ForecastFreshness(
        state=state,
        reference_time=reference_time,
        age_seconds=age_seconds,
    )
