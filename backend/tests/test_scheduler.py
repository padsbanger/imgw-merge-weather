from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.scheduler import AutomaticRefreshScheduler


class StubRefreshCoordinator:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.origins: list[str] = []

    async def start(self, *, origin: str = "manual") -> bool:
        self.origins.append(origin)
        return self.accepted


def test_disabled_scheduler_has_no_job_or_next_run(tmp_path: Path) -> None:
    scheduler = AutomaticRefreshScheduler(
        Settings(data_dir=tmp_path, scheduler_enabled=False),
        StubRefreshCoordinator(),
    )

    scheduler.start()

    assert scheduler.enabled is False
    assert scheduler.state == "disabled"
    assert scheduler.next_run_at is None


def test_invalid_scheduler_cron_fails_startup_clearly(tmp_path: Path) -> None:
    scheduler = AutomaticRefreshScheduler(
        Settings(
            data_dir=tmp_path,
            scheduler_enabled=True,
            scheduler_cron="not a cron expression",
        ),
        StubRefreshCoordinator(),
    )

    with pytest.raises(ValueError, match="Wrong number of fields"):
        scheduler.start()


@pytest.mark.asyncio
async def test_enabled_scheduler_exposes_aware_next_run_and_starts_refresh(
    tmp_path: Path,
) -> None:
    coordinator = StubRefreshCoordinator()
    scheduler = AutomaticRefreshScheduler(
        Settings(
            data_dir=tmp_path,
            scheduler_enabled=True,
            scheduler_cron="2 * * * *",
        ),
        coordinator,
    )

    scheduler.start()
    try:
        assert scheduler.enabled is True
        assert scheduler.state == "running"
        assert scheduler.next_run_at is not None
        assert scheduler.next_run_at.tzinfo is not None

        await scheduler.run_scheduled_refresh()
        assert coordinator.origins == ["scheduled"]
    finally:
        scheduler.shutdown()

    assert scheduler.state == "stopped"


@pytest.mark.asyncio
async def test_scheduler_logs_refresh_skipped_when_work_is_active(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = StubRefreshCoordinator(accepted=False)
    scheduler = AutomaticRefreshScheduler(
        Settings(data_dir=tmp_path, scheduler_enabled=True),
        coordinator,
    )

    with caplog.at_level("INFO"):
        await scheduler.run_scheduled_refresh()

    assert "event=scheduled_refresh_skipped reason=refresh_in_progress" in caplog.text
