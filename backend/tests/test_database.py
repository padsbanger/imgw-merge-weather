from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.database import SCHEMA_VERSION, Database, ForecastRepository, VideoRepository
from app.models import (
    ForecastFrame,
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)
from app.persistence import initialize_forecast_persistence, write_forecast_manifest

START = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


def make_run(
    run_id: str,
    *,
    status: ForecastRunStatus = ForecastRunStatus.COMPLETED,
    discovered_at: datetime = START,
) -> ForecastRun:
    frame_status = (
        FrameValidationStatus.VALID
        if status == ForecastRunStatus.COMPLETED
        else FrameValidationStatus.PENDING
    )
    downloaded_frames = int(frame_status == FrameValidationStatus.VALID)
    return ForecastRun(
        run_id=run_id,
        discovered_at=discovered_at,
        updated_at=discovered_at,
        requested_start_time=START,
        resolved_start_time=START,
        forecast_end_time=START,
        interval_minutes=10,
        forecast_hours=8,
        expected_frames=1,
        downloaded_frames=downloaded_frames,
        coverage=float(downloaded_frames),
        allow_missing_frames=False,
        minimum_frame_coverage=0.9,
        status=status,
        frames=[
            ForecastFrame(
                frame_index=0,
                forecast_time=START,
                source_url="https://cmm.imgw.pl/frame.jpg",
                local_filename="frames/frame_000.jpg",
                width=1700 if downloaded_frames else None,
                height=1600 if downloaded_frames else None,
                size_bytes=455_588 if downloaded_frames else None,
                sha256="a" * 64 if downloaded_frames else None,
                validation_status=frame_status,
            )
        ],
    )


def make_video(
    video_id: str = "video_12345678",
    *,
    status: VideoGenerationStatus = VideoGenerationStatus.COMPLETED,
) -> VideoGeneration:
    completed = status == VideoGenerationStatus.COMPLETED
    return VideoGeneration(
        video_id=video_id,
        run_id="merge_older",
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
        duration_seconds=1.0 if completed else None,
        size_bytes=2048 if completed else None,
    )


def test_database_initialization_creates_versioned_schema_and_indexes(tmp_path: Path) -> None:
    database = Database(tmp_path / "state" / "app.db")

    database.initialize()
    database.initialize()

    assert database.schema_version() == SCHEMA_VERSION
    with sqlite3.connect(database.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert {
        "forecast_runs",
        "forecast_frames",
        "application_state",
        "video_generations",
    } <= tables
    assert {
        "forecast_runs_latest_completed_idx",
        "forecast_runs_discovered_idx",
        "forecast_frames_forecast_time_idx",
        "video_generations_created_idx",
        "video_generations_run_idx",
        "video_generations_active_idx",
    } <= indexes


def test_database_migrates_existing_version_one_database_forward(tmp_path: Path) -> None:
    database = Database(tmp_path / "state" / "app.db")
    with database.connect() as connection:
        database._apply_version_1(connection)

    assert database.schema_version() == 1
    database.initialize()

    assert database.schema_version() == 3
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'video_generations'"
        ).fetchone() == ("video_generations",)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(video_generations)").fetchall()
        }
    assert {"start_frame_index", "end_frame_index", "timestamp_overlay"} <= columns


def test_repository_round_trips_runs_frames_and_application_state(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "app.db"
    database = Database(database_path)
    database.initialize()
    repository = ForecastRepository(database)
    older = make_run("merge_older")
    newer = make_run("merge_newer", discovered_at=START + timedelta(minutes=10))

    repository.upsert_run(older)
    repository.upsert_run(newer)
    repository.set_application_state("last_refresh", "merge_newer")

    restarted_repository = ForecastRepository(Database(database_path))
    loaded = restarted_repository.get_run("merge_newer")
    assert loaded == newer
    assert [run.run_id for run in restarted_repository.list_runs()] == [
        "merge_newer",
        "merge_older",
    ]
    assert restarted_repository.get_latest_completed_run() == newer
    assert restarted_repository.has_completed_run() is True
    assert restarted_repository.get_application_state("last_refresh") == "merge_newer"


def test_video_repository_round_trips_lists_and_recovers_active_generations(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    ForecastRepository(database).upsert_run(make_run("merge_older"))
    repository = VideoRepository(database)
    completed = make_video()
    rendering = make_video(
        "video_abcdefgh",
        status=VideoGenerationStatus.RENDERING,
    )
    rendering.created_at = START + timedelta(seconds=1)
    rendering.updated_at = rendering.created_at
    repository.upsert(completed)
    repository.upsert(rendering)

    assert repository.get(completed.video_id) == completed
    assert [video.video_id for video in repository.list(run_id="merge_older")] == [
        rendering.video_id,
        completed.video_id,
    ]
    assert repository.get_active(
        run_id="merge_older", mode=VideoMode.SOURCE, fps=5
    ) == rendering

    recovered = repository.recover_interrupted(recovered_at=START + timedelta(minutes=1))

    assert [video.video_id for video in recovered] == [rendering.video_id]
    failed = repository.get(rendering.video_id)
    assert failed is not None
    assert failed.status == VideoGenerationStatus.FAILED
    assert failed.error == "Interrupted by application restart"


def test_startup_imports_legacy_manifest_only_once_and_database_survives_restart(
    tmp_path: Path,
) -> None:
    runs_directory = tmp_path / "runs"
    run_directory = runs_directory / "merge_existing"
    run_directory.mkdir(parents=True)
    write_forecast_manifest(make_run("merge_existing"), run_directory)
    database_path = tmp_path / "state" / "app.db"

    repository, first_report = initialize_forecast_persistence(
        database_path=database_path,
        runs_directory=runs_directory,
    )
    (run_directory / "manifest.json").unlink()
    restarted_repository, second_report = initialize_forecast_persistence(
        database_path=database_path,
        runs_directory=runs_directory,
    )

    assert first_report.imported_runs == 1
    assert second_report.imported_runs == 0
    assert repository.get_run("merge_existing") is not None
    assert restarted_repository.get_run("merge_existing") is not None


def test_startup_recovers_interrupted_run_in_database_and_manifest(tmp_path: Path) -> None:
    runs_directory = tmp_path / "runs"
    run_directory = runs_directory / "merge_interrupted"
    run_directory.mkdir(parents=True)
    write_forecast_manifest(
        make_run("merge_interrupted", status=ForecastRunStatus.DOWNLOADING),
        run_directory,
    )

    repository, report = initialize_forecast_persistence(
        database_path=tmp_path / "state" / "app.db",
        runs_directory=runs_directory,
    )

    recovered = repository.get_run("merge_interrupted")
    manifest = json.loads((run_directory / "manifest.json").read_text())
    assert report.recovered_runs == ("merge_interrupted",)
    assert recovered is not None
    assert recovered.status == ForecastRunStatus.FAILED
    assert recovered.error == "Interrupted by application restart"
    assert recovered.frames[0].validation_status == FrameValidationStatus.FAILED
    assert recovered.missing_timestamps == [START]
    assert manifest["status"] == "failed"
    assert manifest["frames"][0]["validation_status"] == "failed"


def test_startup_skips_invalid_or_mismatched_manifest(tmp_path: Path) -> None:
    runs_directory = tmp_path / "runs"
    invalid_directory = runs_directory / "merge_invalid"
    invalid_directory.mkdir(parents=True)
    (invalid_directory / "manifest.json").write_text("not-json")
    mismatched_directory = runs_directory / "merge_directory"
    mismatched_directory.mkdir()
    write_forecast_manifest(make_run("merge_other"), mismatched_directory)

    repository, report = initialize_forecast_persistence(
        database_path=tmp_path / "state" / "app.db",
        runs_directory=runs_directory,
    )

    assert report.skipped_manifests == 2
    assert repository.list_runs() == []
