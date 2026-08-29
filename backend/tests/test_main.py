from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database, ForecastRepository
from app.main import create_app
from app.models import ForecastRun, ForecastRunStatus


def test_health_endpoint(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "imgw-merge-weather",
        "version": "0.1.0",
    }


def test_status_reports_current_milestone_without_ingested_weather_data(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))

    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    server_time = datetime.fromisoformat(payload.pop("server_time").replace("Z", "+00:00"))
    assert server_time.tzinfo is not None
    assert payload == {
        "service": "imgw-merge-weather",
        "version": "0.1.0",
        "milestone": 9,
        "weather_data_available": False,
        "refresh_in_progress": False,
        "last_refresh_at": None,
        "last_refresh_status": None,
        "last_imgw_error": None,
        "scheduler": {"enabled": False, "state": "disabled", "next_run_at": None},
    }


def test_status_detects_completed_database_run(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    ForecastRepository(database).upsert_run(
        ForecastRun(
            run_id="merge_completed",
            discovered_at=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
            requested_start_time=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
            resolved_start_time=datetime(2026, 8, 29, 10, 0, tzinfo=UTC),
            forecast_end_time=datetime(2026, 8, 29, 18, 0, tzinfo=UTC),
            interval_minutes=10,
            forecast_hours=8,
            expected_frames=49,
            downloaded_frames=49,
            coverage=1,
            allow_missing_frames=False,
            minimum_frame_coverage=0.9,
            status=ForecastRunStatus.COMPLETED,
        )
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["weather_data_available"] is True
