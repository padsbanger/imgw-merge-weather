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
    VideoInterpolation,
    VideoMode,
    VideoSmoothing,
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
        source_fps=3,
        output_fps=30,
        interpolation=VideoInterpolation.CROSSFADE,
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
        self.calls: list[
            tuple[
                str,
                VideoMode,
                int | None,
                int | None,
                VideoSmoothing | None,
                int | None,
                int | None,
                bool,
            ]
        ] = []

    async def start(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        source_fps: int | None,
        output_fps: int | None,
        interpolation: VideoSmoothing | None,
        start_frame_index: int | None,
        end_frame_index: int | None,
        timestamp_overlay: bool,
    ) -> VideoGeneration:
        self.calls.append(
            (
                run_id,
                mode,
                source_fps,
                output_fps,
                interpolation,
                start_frame_index,
                end_frame_index,
                timestamp_overlay,
            )
        )
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
            json={
                "mode": "1:1",
                "source_fps": 5,
                "output_fps": 60,
                "interpolation": "none",
                "start_frame_index": 2,
                "end_frame_index": 20,
                "timestamp_overlay": True,
            },
        )
        invalid_mode = client.post(
            "/api/runs/merge_video_api/videos", json={"mode": "stretch"}
        )
        invalid_source_fps = client.post(
            "/api/runs/merge_video_api/videos", json={"source_fps": 0}
        )
        invalid_output_fps = client.post(
            "/api/runs/merge_video_api/videos", json={"output_fps": 61}
        )
        invalid_interpolation = client.post(
            "/api/runs/merge_video_api/videos", json={"interpolation": "motion"}
        )
        invalid_range = client.post(
            "/api/runs/merge_video_api/videos",
            json={"start_frame_index": 20, "end_frame_index": 2},
        )
        missing_run = client.post(
            "/api/runs/merge_unknown/videos", json={"mode": "source"}
        )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["file_url"] is None
    assert response.json()["source_fps"] == 3
    assert response.json()["output_fps"] == 30
    assert response.json()["interpolation"] == "crossfade"
    assert coordinator.calls == [
        (
            "merge_video_api",
            VideoMode.SQUARE,
            5,
            60,
            VideoSmoothing.NONE,
            2,
            20,
            True,
        )
    ]
    assert invalid_mode.status_code == 422
    assert invalid_source_fps.status_code == 422
    assert invalid_output_fps.status_code == 422
    assert invalid_interpolation.status_code == 422
    assert invalid_range.status_code == 422
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
        pending_delete = client.delete(f"/api/videos/{pending.video_id}")
        deleted = client.delete(f"/api/videos/{completed.video_id}")
        deleted_detail = client.get(f"/api/videos/{completed.video_id}")
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
    assert pending_delete.status_code == 409
    assert deleted.json() == {"video_id": completed.video_id, "status": "deleted"}
    assert not output_path.exists()
    assert deleted_detail.status_code == 404
    assert missing.status_code == 404
