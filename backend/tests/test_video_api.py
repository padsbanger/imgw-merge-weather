from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database, ForecastRepository
from app.main import create_app
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)

START = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def forecast_run() -> ForecastRun:
    return ForecastRun(
        run_id="merge_video_api",
        discovered_at=START,
        updated_at=START,
        requested_start_time=START,
        resolved_start_time=START,
        forecast_end_time=START + timedelta(hours=8),
        interval_minutes=10,
        forecast_hours=8,
        expected_frames=49,
        downloaded_frames=49,
        coverage=1,
        allow_missing_frames=False,
        minimum_frame_coverage=0.9,
        status=ForecastRunStatus.COMPLETED,
    )


def video(
    video_id: str,
    *,
    status: VideoGenerationStatus,
) -> VideoGeneration:
    completed = status == VideoGenerationStatus.COMPLETED
    return VideoGeneration(
        video_id=video_id,
        run_id="merge_video_api",
        created_at=START,
        updated_at=START,
        status=status,
        mode=VideoMode.SOURCE,
        fps=5,
        codec="libx264",
        crf=20,
        preset="medium",
        output_filename=f"{video_id}.mp4",
        width=1700 if completed else None,
        height=1600 if completed else None,
        duration_seconds=9.8 if completed else None,
        size_bytes=4096 if completed else None,
    )


class StubVideoCoordinator:
    def __init__(self, pending: VideoGeneration) -> None:
        self.pending = pending
        self.calls: list[tuple[str, VideoMode, int | None]] = []

    async def start(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        fps: int | None,
    ) -> VideoGeneration:
        self.calls.append((run_id, mode, fps))
        return self.pending


def prepare_app(tmp_path: Path) -> tuple[object, Settings]:
    settings = Settings(data_dir=tmp_path)
    settings.ensure_data_directories()
    database = Database(settings.database_path)
    database.initialize()
    ForecastRepository(database).upsert_run(forecast_run())
    return create_app(settings), settings


def test_video_api_starts_typed_background_generation_and_validates_input(
    tmp_path: Path,
) -> None:
    app, _ = prepare_app(tmp_path)
    pending = video("video_pending1", status=VideoGenerationStatus.PENDING)

    with TestClient(app) as client:
        coordinator = StubVideoCoordinator(pending)
        app.state.video_coordinator = coordinator
        response = client.post(
            "/api/runs/merge_video_api/videos",
            json={"mode": "1:1", "fps": 7},
        )
        invalid_mode = client.post(
            "/api/runs/merge_video_api/videos", json={"mode": "stretch"}
        )
        invalid_fps = client.post(
            "/api/runs/merge_video_api/videos", json={"fps": 0}
        )
        missing_run = client.post(
            "/api/runs/merge_unknown/videos", json={"mode": "source"}
        )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["file_url"] is None
    assert coordinator.calls == [("merge_video_api", VideoMode.SQUARE, 7)]
    assert invalid_mode.status_code == 422
    assert invalid_fps.status_code == 422
    assert missing_run.status_code == 404


def test_video_api_lists_details_and_serves_only_completed_mp4(tmp_path: Path) -> None:
    app, settings = prepare_app(tmp_path)

    with TestClient(app) as client:
        repository = app.state.video_repository
        completed = video("video_complete1", status=VideoGenerationStatus.COMPLETED)
        pending = video("video_pending2", status=VideoGenerationStatus.PENDING)
        repository.upsert(completed)
        repository.upsert(pending)
        output_path = settings.output_dir / completed.output_filename
        output_path.write_bytes(b"browser-compatible-mp4")

        listing = client.get("/api/videos?run_id=merge_video_api")
        detail = client.get(f"/api/videos/{completed.video_id}")
        file_response = client.get(f"/api/videos/{completed.video_id}/file")
        pending_file = client.get(f"/api/videos/{pending.video_id}/file")
        missing = client.get("/api/videos/video_missing1")

    assert listing.status_code == 200
    assert listing.json()["count"] == 2
    assert {item["video_id"] for item in listing.json()["videos"]} == {
        completed.video_id,
        pending.video_id,
    }
    assert detail.json()["file_url"] == f"/api/videos/{completed.video_id}/file"
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "video/mp4"
    assert file_response.content == b"browser-compatible-mp4"
    assert pending_file.status_code == 409
    assert missing.status_code == 404
