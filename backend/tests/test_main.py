from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
    assert response.json() == {
        "service": "imgw-merge-weather",
        "version": "0.1.0",
        "milestone": 1,
        "weather_data_available": False,
    }
