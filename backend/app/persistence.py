"""Filesystem manifest reconciliation around the SQLite metadata store."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.database import Database, ForecastRepository
from app.models import ForecastRun

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersistenceStartupReport:
    imported_runs: int
    recovered_runs: tuple[str, ...]
    skipped_manifests: int


def write_forecast_manifest(run: ForecastRun, run_directory: Path) -> None:
    """Atomically replace a run manifest without exposing a partial JSON file."""

    manifest_path = run_directory / "manifest.json"
    payload = run.model_dump_json(indent=2).encode("utf-8") + b"\n"
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".manifest.",
            suffix=".tmp",
            dir=run_directory,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, manifest_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def initialize_forecast_persistence(
    *,
    database_path: Path,
    runs_directory: Path,
) -> tuple[ForecastRepository, PersistenceStartupReport]:
    """Migrate SQLite, import legacy manifests, and fail interrupted operations."""

    database = Database(database_path)
    database.initialize()
    repository = ForecastRepository(database)
    imported_runs, skipped_manifests = _import_missing_manifests(repository, runs_directory)
    recovered = repository.recover_interrupted_runs()

    runs_root = runs_directory.resolve()
    for run in recovered:
        run_directory = (runs_root / run.run_id).resolve()
        if run_directory.parent == runs_root and run_directory.is_dir():
            write_forecast_manifest(run, run_directory)

    report = PersistenceStartupReport(
        imported_runs=imported_runs,
        recovered_runs=tuple(run.run_id for run in recovered),
        skipped_manifests=skipped_manifests,
    )
    LOGGER.info(
        "event=persistence_ready schema_version=%d imported_runs=%d recovered_runs=%d "
        "skipped_manifests=%d",
        database.schema_version(),
        report.imported_runs,
        len(report.recovered_runs),
        report.skipped_manifests,
    )
    return repository, report


def _import_missing_manifests(
    repository: ForecastRepository,
    runs_directory: Path,
) -> tuple[int, int]:
    imported = 0
    skipped = 0
    if not runs_directory.is_dir():
        return imported, skipped

    for manifest_path in sorted(runs_directory.glob("*/manifest.json")):
        try:
            run = ForecastRun.model_validate_json(manifest_path.read_bytes())
            if run.run_id != manifest_path.parent.name:
                raise ValueError("manifest run ID does not match its directory")
            if repository.get_run(run.run_id) is not None:
                continue
            repository.upsert_run(run)
            imported += 1
        except (OSError, ValueError, ValidationError) as error:
            skipped += 1
            LOGGER.warning(
                "event=manifest_import_skipped manifest=%s error=%s",
                manifest_path,
                error,
            )
    return imported, skipped
