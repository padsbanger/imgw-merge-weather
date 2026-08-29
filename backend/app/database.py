"""Versioned SQLite persistence for forecast metadata."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.models import (
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)

SCHEMA_VERSION = 3
INTERRUPTED_RUN_STATUSES = (
    ForecastRunStatus.PENDING,
    ForecastRunStatus.PROBING,
    ForecastRunStatus.DOWNLOADING,
)


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database was created by a newer application version."""


class Database:
    """Own connections and apply forward-only, in-process schema migrations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"Database schema version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if version == 0:
                self._apply_version_1(connection)
                version = 1
            if version == 1:
                self._apply_version_2(connection)
                version = 2
            if version == 2:
                self._apply_version_3(connection)

    @staticmethod
    def _apply_version_1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE forecast_runs (
                run_id TEXT PRIMARY KEY,
                manifest_version INTEGER NOT NULL,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                product TEXT NOT NULL,
                canonical_timezone TEXT NOT NULL,
                filename_timezone TEXT NOT NULL,
                display_timezone TEXT NOT NULL,
                requested_start_time TEXT NOT NULL,
                resolved_start_time TEXT,
                forecast_end_time TEXT,
                interval_minutes INTEGER NOT NULL CHECK (interval_minutes > 0),
                forecast_hours INTEGER NOT NULL CHECK (forecast_hours > 0),
                expected_frames INTEGER NOT NULL CHECK (expected_frames >= 0),
                downloaded_frames INTEGER NOT NULL CHECK (downloaded_frames >= 0),
                coverage REAL NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
                allow_missing_frames INTEGER NOT NULL CHECK (allow_missing_frames IN (0, 1)),
                minimum_frame_coverage REAL NOT NULL
                    CHECK (minimum_frame_coverage >= 0 AND minimum_frame_coverage <= 1),
                status TEXT NOT NULL,
                missing_timestamps_json TEXT NOT NULL DEFAULT '[]',
                error TEXT
            );

            CREATE TABLE forecast_frames (
                run_id TEXT NOT NULL,
                frame_index INTEGER NOT NULL CHECK (frame_index >= 0),
                forecast_time TEXT NOT NULL,
                source_url TEXT NOT NULL,
                local_filename TEXT NOT NULL,
                width INTEGER CHECK (width > 0),
                height INTEGER CHECK (height > 0),
                size_bytes INTEGER CHECK (size_bytes >= 0),
                sha256 TEXT,
                validation_status TEXT NOT NULL,
                error TEXT,
                PRIMARY KEY (run_id, frame_index),
                UNIQUE (run_id, forecast_time),
                FOREIGN KEY (run_id) REFERENCES forecast_runs(run_id) ON DELETE CASCADE
            );

            CREATE INDEX forecast_runs_latest_completed_idx
                ON forecast_runs(resolved_start_time DESC, discovered_at DESC)
                WHERE status = 'completed';
            CREATE INDEX forecast_runs_discovered_idx
                ON forecast_runs(discovered_at DESC);
            CREATE INDEX forecast_frames_forecast_time_idx
                ON forecast_frames(run_id, forecast_time);

            CREATE TABLE application_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            PRAGMA user_version = 1;
            COMMIT;
            """
        )

    def schema_version(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _apply_version_2(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE video_generations (
                video_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                fps INTEGER NOT NULL CHECK (fps >= 1 AND fps <= 30),
                codec TEXT NOT NULL,
                crf INTEGER NOT NULL CHECK (crf >= 0 AND crf <= 51),
                preset TEXT NOT NULL,
                output_filename TEXT NOT NULL UNIQUE,
                width INTEGER CHECK (width > 0),
                height INTEGER CHECK (height > 0),
                duration_seconds REAL CHECK (duration_seconds > 0),
                size_bytes INTEGER CHECK (size_bytes >= 0),
                error TEXT,
                FOREIGN KEY (run_id) REFERENCES forecast_runs(run_id) ON DELETE RESTRICT
            );

            CREATE INDEX video_generations_created_idx
                ON video_generations(created_at DESC);
            CREATE INDEX video_generations_run_idx
                ON video_generations(run_id, created_at DESC);
            CREATE INDEX video_generations_active_idx
                ON video_generations(run_id, mode, fps)
                WHERE status IN ('pending', 'rendering');

            PRAGMA user_version = 2;
            COMMIT;
            """
        )

    @staticmethod
    def _apply_version_3(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            ALTER TABLE video_generations
                ADD COLUMN start_frame_index INTEGER NOT NULL DEFAULT 0
                CHECK (start_frame_index >= 0);
            ALTER TABLE video_generations
                ADD COLUMN end_frame_index INTEGER CHECK (end_frame_index >= 0);
            ALTER TABLE video_generations
                ADD COLUMN timestamp_overlay INTEGER NOT NULL DEFAULT 0
                CHECK (timestamp_overlay IN (0, 1));

            PRAGMA user_version = 3;
            COMMIT;
            """
        )


class ForecastRepository:
    """Persist and reconstruct forecast aggregates without exposing SQLite rows."""

    _RUN_COLUMNS = (
        "run_id",
        "manifest_version",
        "discovered_at",
        "updated_at",
        "source",
        "product",
        "canonical_timezone",
        "filename_timezone",
        "display_timezone",
        "requested_start_time",
        "resolved_start_time",
        "forecast_end_time",
        "interval_minutes",
        "forecast_hours",
        "expected_frames",
        "downloaded_frames",
        "coverage",
        "allow_missing_frames",
        "minimum_frame_coverage",
        "status",
        "missing_timestamps_json",
        "error",
    )

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_run(self, run: ForecastRun) -> None:
        payload = run.model_dump(mode="json", exclude={"frames", "missing_timestamps"})
        payload["allow_missing_frames"] = int(run.allow_missing_frames)
        payload["missing_timestamps_json"] = json.dumps(
            run.model_dump(mode="json", include={"missing_timestamps"})["missing_timestamps"]
        )
        columns = ", ".join(self._RUN_COLUMNS)
        values = ", ".join(f":{column}" for column in self._RUN_COLUMNS)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in self._RUN_COLUMNS
            if column != "run_id"
        )

        with self.database.connect() as connection:
            connection.execute(
                f"INSERT INTO forecast_runs ({columns}) VALUES ({values}) "
                f"ON CONFLICT(run_id) DO UPDATE SET {updates}",
                payload,
            )
            connection.execute("DELETE FROM forecast_frames WHERE run_id = ?", (run.run_id,))
            connection.executemany(
                """
                INSERT INTO forecast_frames (
                    run_id, frame_index, forecast_time, source_url, local_filename,
                    width, height, size_bytes, sha256, validation_status, error
                ) VALUES (
                    :run_id, :frame_index, :forecast_time, :source_url, :local_filename,
                    :width, :height, :size_bytes, :sha256, :validation_status, :error
                )
                """,
                [
                    {"run_id": run.run_id, **frame.model_dump(mode="json")}
                    for frame in run.frames
                ],
            )

    def get_run(self, run_id: str) -> ForecastRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM forecast_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return self._hydrate_run(connection, row) if row is not None else None

    def list_runs(self, *, limit: int = 100) -> list[ForecastRun]:
        if not 1 <= limit <= 1000:
            raise ValueError("Run list limit must be between 1 and 1000")
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM forecast_runs ORDER BY discovered_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._hydrate_run(connection, row) for row in rows]

    def get_latest_completed_run(self) -> ForecastRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM forecast_runs
                WHERE status = 'completed'
                ORDER BY resolved_start_time DESC, discovered_at DESC
                LIMIT 1
                """
            ).fetchone()
            return self._hydrate_run(connection, row) if row is not None else None

    def has_completed_run(self) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM forecast_runs WHERE status = 'completed' LIMIT 1"
            ).fetchone()
            return row is not None

    def recover_interrupted_runs(
        self,
        *,
        recovered_at: datetime | None = None,
    ) -> list[ForecastRun]:
        timestamp = recovered_at or datetime.now(UTC)
        recovered: list[ForecastRun] = []
        active_statuses = {status.value for status in INTERRUPTED_RUN_STATUSES}
        placeholders = ", ".join("?" for _ in active_statuses)
        with self.database.connect() as connection:
            run_ids = [
                str(row["run_id"])
                for row in connection.execute(
                    f"SELECT run_id FROM forecast_runs WHERE status IN ({placeholders})",
                    tuple(active_statuses),
                ).fetchall()
            ]
        for run_id in run_ids:
            run = self.get_run(run_id)
            if run is None:
                continue
            run.status = ForecastRunStatus.FAILED
            run.updated_at = timestamp
            run.error = "Interrupted by application restart"
            for frame in run.frames:
                if frame.validation_status == FrameValidationStatus.PENDING:
                    frame.validation_status = FrameValidationStatus.FAILED
                    frame.error = "Not completed before application restart"
            run.missing_timestamps = [
                frame.forecast_time
                for frame in run.frames
                if frame.validation_status != FrameValidationStatus.VALID
            ]
            self.upsert_run(run)
            recovered.append(run)
        return recovered

    def set_application_state(
        self,
        key: str,
        value: str,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        if not key or len(key) > 128:
            raise ValueError("Application state key must contain 1 to 128 characters")
        timestamp = (updated_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO application_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )

    def get_application_state(self, key: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM application_state WHERE key = ?", (key,)
            ).fetchone()
            return str(row["value"]) if row is not None else None

    @staticmethod
    def _hydrate_run(connection: sqlite3.Connection, row: sqlite3.Row) -> ForecastRun:
        payload = dict(row)
        payload["allow_missing_frames"] = bool(payload["allow_missing_frames"])
        payload["missing_timestamps"] = json.loads(payload.pop("missing_timestamps_json"))
        payload["frames"] = [
            dict(frame)
            for frame in connection.execute(
                """
                SELECT frame_index, forecast_time, source_url, local_filename,
                       width, height, size_bytes, sha256, validation_status, error
                FROM forecast_frames
                WHERE run_id = ?
                ORDER BY frame_index
                """,
                (payload["run_id"],),
            ).fetchall()
        ]
        return ForecastRun.model_validate(payload)


class VideoRepository:
    """Persist video-generation lifecycle separately from forecast ingestion."""

    _COLUMNS = (
        "video_id",
        "run_id",
        "created_at",
        "updated_at",
        "status",
        "mode",
        "fps",
        "codec",
        "crf",
        "preset",
        "output_filename",
        "start_frame_index",
        "end_frame_index",
        "timestamp_overlay",
        "width",
        "height",
        "duration_seconds",
        "size_bytes",
        "error",
    )

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert(self, video: VideoGeneration) -> None:
        payload = video.model_dump(mode="json")
        payload["timestamp_overlay"] = int(video.timestamp_overlay)
        columns = ", ".join(self._COLUMNS)
        values = ", ".join(f":{column}" for column in self._COLUMNS)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in self._COLUMNS
            if column != "video_id"
        )
        with self.database.connect() as connection:
            connection.execute(
                f"INSERT INTO video_generations ({columns}) VALUES ({values}) "
                f"ON CONFLICT(video_id) DO UPDATE SET {updates}",
                payload,
            )

    def get(self, video_id: str) -> VideoGeneration | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM video_generations WHERE video_id = ?", (video_id,)
            ).fetchone()
        return self._hydrate(row) if row is not None else None

    def list(
        self,
        *,
        limit: int = 100,
        run_id: str | None = None,
    ) -> list[VideoGeneration]:
        if not 1 <= limit <= 1000:
            raise ValueError("Video list limit must be between 1 and 1000")
        query = "SELECT * FROM video_generations"
        parameters: tuple[object, ...]
        if run_id is None:
            parameters = (limit,)
        else:
            query += " WHERE run_id = ?"
            parameters = (run_id, limit)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._hydrate(row) for row in rows]

    def get_active(
        self,
        *,
        run_id: str,
        mode: VideoMode,
        fps: int,
    ) -> VideoGeneration | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM video_generations
                WHERE run_id = ? AND mode = ? AND fps = ?
                  AND status IN ('pending', 'rendering')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id, mode.value, fps),
            ).fetchone()
        return self._hydrate(row) if row is not None else None

    def delete(self, video_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM video_generations WHERE video_id = ?", (video_id,)
            )
            return cursor.rowcount > 0

    def recover_interrupted(
        self,
        *,
        recovered_at: datetime | None = None,
    ) -> list[VideoGeneration]:
        timestamp = recovered_at or datetime.now(UTC)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM video_generations
                WHERE status IN ('pending', 'rendering')
                ORDER BY created_at
                """
            ).fetchall()
        recovered: list[VideoGeneration] = []
        for row in rows:
            video = self._hydrate(row)
            video.status = VideoGenerationStatus.FAILED
            video.updated_at = timestamp
            video.error = "Interrupted by application restart"
            self.upsert(video)
            recovered.append(video)
        return recovered

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> VideoGeneration:
        payload = dict(row)
        payload["timestamp_overlay"] = bool(payload["timestamp_overlay"])
        return VideoGeneration.model_validate(payload)
