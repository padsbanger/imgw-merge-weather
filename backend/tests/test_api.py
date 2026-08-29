from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database, ForecastRepository
from app.main import create_app
from app.models import (
    ForecastFrame,
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
)

NOW = datetime.now(UTC).replace(microsecond=0)


class StubRefreshCoordinator:
    def __init__(self, *, accepted: bool, is_running: bool = False) -> None:
        self.accepted = accepted
        self.is_running = is_running
        self.calls = 0
        self.last_refresh_at = None
        self.last_refresh_status = None
        self.last_imgw_error = None

    async def start(self) -> bool:
        self.calls += 1
        return self.accepted


def make_run(
    run_id: str,
    *,
    discovered_at: datetime,
    status: ForecastRunStatus,
    local_filename: str = "frames/frame_000.jpg",
) -> ForecastRun:
    valid = status == ForecastRunStatus.COMPLETED
    return ForecastRun(
        run_id=run_id,
        discovered_at=discovered_at,
        updated_at=discovered_at,
        requested_start_time=NOW,
        resolved_start_time=NOW,
        forecast_end_time=NOW + timedelta(hours=8),
        interval_minutes=10,
        forecast_hours=8,
        expected_frames=1,
        downloaded_frames=int(valid),
        coverage=float(valid),
        allow_missing_frames=False,
        minimum_frame_coverage=0.9,
        status=status,
        error=None if valid else "test failure",
        frames=[
            ForecastFrame(
                frame_index=0,
                forecast_time=NOW,
                source_url="https://cmm.imgw.pl/source-frame.jpg",
                local_filename=local_filename,
                width=1700 if valid else None,
                height=1600 if valid else None,
                size_bytes=12 if valid else None,
                sha256="a" * 64 if valid else None,
                validation_status=(
                    FrameValidationStatus.VALID if valid else FrameValidationStatus.MISSING
                ),
                error=None if valid else "HTTP 404",
            )
        ],
    )


def prepare_app(tmp_path: Path) -> tuple[object, Settings]:
    settings = Settings(data_dir=tmp_path)
    settings.ensure_data_directories()
    database = Database(settings.database_path)
    database.initialize()
    repository = ForecastRepository(database)
    completed = make_run(
        "merge_completed",
        discovered_at=NOW,
        status=ForecastRunStatus.COMPLETED,
    )
    failed = make_run(
        "merge_failed",
        discovered_at=NOW + timedelta(minutes=1),
        status=ForecastRunStatus.FAILED,
    )
    repository.upsert_run(completed)
    repository.upsert_run(failed)
    frame_path = settings.runs_dir / completed.run_id / "frames" / "frame_000.jpg"
    frame_path.parent.mkdir(parents=True)
    frame_path.write_bytes(b"jpeg-content")
    return create_app(settings), settings


def test_run_list_latest_and_detail_expose_typed_forecast_contract(tmp_path: Path) -> None:
    app, _ = prepare_app(tmp_path)

    with TestClient(app) as client:
        list_response = client.get("/api/runs")
        latest_response = client.get("/api/runs/latest")
        detail_response = client.get("/api/runs/merge_failed")

    assert list_response.status_code == 200
    listing = list_response.json()
    assert listing["count"] == 2
    assert listing["latest_run_id"] == "merge_completed"
    assert [run["run_id"] for run in listing["runs"]] == [
        "merge_failed",
        "merge_completed",
    ]
    assert listing["runs"][1]["progress"] == {
        "downloaded_frames": 1,
        "expected_frames": 1,
        "fraction": 1.0,
    }
    assert listing["runs"][1]["freshness"]["state"] == "FRESH"
    assert "frames" not in listing["runs"][1]

    assert latest_response.status_code == 200
    latest = latest_response.json()
    assert latest["run_id"] == "merge_completed"
    assert latest["frames"][0]["frame_url"] == (
        "/api/runs/merge_completed/frames/0"
    )
    assert latest["frames"][0]["source_url"].startswith("https://cmm.imgw.pl/")
    assert "local_filename" not in latest["frames"][0]

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "failed"
    assert detail_response.json()["frames"][0]["validation_status"] == "missing"


def test_run_api_returns_clear_not_found_and_validation_responses(tmp_path: Path) -> None:
    app, _ = prepare_app(tmp_path)

    with TestClient(app) as client:
        missing = client.get("/api/runs/merge_missing")
        invalid_id = client.get("/api/runs/MERGE_INVALID")
        invalid_limit = client.get("/api/runs?limit=0")
        missing_frame = client.get("/api/runs/merge_failed/frames/0")
        invalid_frame_index = client.get("/api/runs/merge_completed/frames/10001")

    assert missing.status_code == 404
    assert invalid_id.status_code == 422
    assert invalid_limit.status_code == 422
    assert missing_frame.status_code == 404
    assert invalid_frame_index.status_code == 422


def test_frame_endpoint_serves_only_valid_contained_immutable_file(tmp_path: Path) -> None:
    app, settings = prepare_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/runs/merge_completed/frames/0")

        repository = app.state.forecast_repository
        unsafe_run = make_run(
            "merge_unsafe",
            discovered_at=NOW,
            status=ForecastRunStatus.COMPLETED,
            local_filename="../outside.jpg",
        )
        repository.upsert_run(unsafe_run)
        (settings.runs_dir / "outside.jpg").write_bytes(b"must-not-be-served")
        unsafe_response = client.get("/api/runs/merge_unsafe/frames/0")

    assert response.status_code == 200
    assert response.content == b"jpeg-content"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == f'"{"a" * 64}"'
    assert response.headers["x-frame-index"] == "0"
    assert unsafe_response.status_code == 404
    assert unsafe_response.content != b"must-not-be-served"


def test_refresh_endpoint_accepts_background_work_and_rejects_overlap(tmp_path: Path) -> None:
    app, _ = prepare_app(tmp_path)

    with TestClient(app) as client:
        accepted = StubRefreshCoordinator(accepted=True, is_running=True)
        app.state.refresh_coordinator = accepted
        accepted_response = client.post("/api/runs/refresh")
        status_response = client.get("/api/status")

        overlapping = StubRefreshCoordinator(accepted=False, is_running=True)
        app.state.refresh_coordinator = overlapping
        conflict_response = client.post("/api/runs/refresh")

    assert accepted_response.status_code == 202
    assert accepted_response.json()["status"] == "accepted"
    assert accepted.calls == 1
    assert status_response.json()["refresh_in_progress"] is True
    assert conflict_response.status_code == 409
    assert overlapping.calls == 1


def test_latest_returns_404_when_no_completed_run_exists(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))

    with TestClient(app) as client:
        latest = client.get("/api/runs/latest")
        listing = client.get("/api/runs")

    assert latest.status_code == 404
    assert listing.json() == {"runs": [], "count": 0, "latest_run_id": None}
