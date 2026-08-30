from pathlib import Path

from app.config import Settings


def test_ensure_data_directories_creates_expected_layout(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    settings.ensure_data_directories()

    assert settings.runs_dir.is_dir()
    assert settings.output_dir.is_dir()
    assert settings.state_dir.is_dir()


def test_scheduler_defaults_are_conservative_and_configurable(tmp_path: Path) -> None:
    defaults = Settings(data_dir=tmp_path)
    enabled = Settings(
        data_dir=tmp_path,
        scheduler_enabled=True,
        scheduler_cron="*/15 * * * *",
        scheduler_misfire_grace_seconds=90,
    )

    assert defaults.scheduler_enabled is False
    assert defaults.scheduler_cron == "2 * * * *"
    assert enabled.scheduler_enabled is True
    assert enabled.scheduler_cron == "*/15 * * * *"
    assert enabled.scheduler_misfire_grace_seconds == 90


def test_video_smoothing_defaults_are_cpu_friendly(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.video_source_fps == 3
    assert settings.video_output_fps == 30
    assert settings.video_interpolation == "crossfade"
    assert settings.video_auto_generate is False
    assert settings.video_max_concurrent_renders == 1
    assert settings.video_timeout_seconds == 300


def test_forecast_window_includes_two_hours_before_current_cycle(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.forecast_lookback_hours == 2
    assert settings.forecast_hours == 8
