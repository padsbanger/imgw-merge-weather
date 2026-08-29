from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.database import Database, ForecastRepository
from app.forecast import CompleteSequenceProbe
from app.imgw_client import (
    DownloadedFrame,
    FrameMetadata,
    FrameUnavailableError,
    FrameValidationError,
    build_frame_url,
)
from app.models import ForecastRunStatus, FrameValidationStatus
from app.services.ingestion import RUN_ID_PATTERN, ForecastIngestionService, generate_run_id

BASE_URL = "https://cmm.imgw.pl/wp-content/uploads/production/MERGE"
START = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)


class FakeImgwClient:
    def __init__(
        self,
        *,
        missing: set[datetime] | None = None,
        missing_once: set[datetime] | None = None,
        invalid: set[datetime] | None = None,
    ) -> None:
        self.missing = missing or set()
        self.missing_once = missing_once or set()
        self.invalid = invalid or set()
        self.fetch_counts: dict[datetime, int] = {}

    def frame_url(self, timestamp: datetime) -> str:
        return build_frame_url(BASE_URL, timestamp)

    async def fetch_frame(self, timestamp: datetime) -> DownloadedFrame:
        self.fetch_counts[timestamp] = self.fetch_counts.get(timestamp, 0) + 1
        if timestamp in self.missing or (
            timestamp in self.missing_once and self.fetch_counts[timestamp] == 1
        ):
            raise FrameUnavailableError(self.frame_url(timestamp), 404)
        if timestamp in self.invalid:
            raise FrameValidationError(f"Invalid test frame at {timestamp.isoformat()}")

        content = f"validated-frame:{timestamp.isoformat()}".encode()
        return DownloadedFrame(
            metadata=FrameMetadata(
                forecast_time=timestamp,
                source_url=self.frame_url(timestamp),
                content_type="image/jpeg",
                size_bytes=len(content),
                width=1700,
                height=1600,
                image_format="JPEG",
            ),
            content=content,
        )

    async def save_frame(self, frame: DownloadedFrame, destination: Path) -> FrameMetadata:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(frame.content)
        return frame.metadata


def create_service(
    tmp_path: Path,
    client: FakeImgwClient,
    *,
    allow_missing_frames: bool = False,
    minimum_frame_coverage: float = 0.90,
    run_id: str = "merge_test_run",
    max_start_fallback_steps: int = 2,
    repository: ForecastRepository | None = None,
) -> ForecastIngestionService:
    return ForecastIngestionService(
        client=client,  # type: ignore[arg-type]
        data_dir=tmp_path,
        interval_minutes=30,
        forecast_hours=1,
        max_start_fallback_steps=max_start_fallback_steps,
        allow_missing_frames=allow_missing_frames,
        minimum_frame_coverage=minimum_frame_coverage,
        run_id_factory=lambda _: run_id,
        repository=repository,
    )


def read_manifest(tmp_path: Path, run_id: str = "merge_test_run") -> dict[str, object]:
    return json.loads((tmp_path / "runs" / run_id / "manifest.json").read_text())


def test_generated_run_id_is_path_safe() -> None:
    run_id = generate_run_id(START)

    assert run_id.startswith("merge_20260829t100000z_")
    assert RUN_ID_PATTERN.fullmatch(run_id)


@pytest.mark.asyncio
async def test_ingests_complete_latest_run_and_persists_manifest(tmp_path: Path) -> None:
    client = FakeImgwClient()
    service = create_service(tmp_path, client)

    run = await service.ingest(now=START + timedelta(minutes=7))

    assert run.status == ForecastRunStatus.COMPLETED
    assert run.resolved_start_time == START
    assert run.forecast_end_time == START + timedelta(hours=1)
    assert run.expected_frames == 3
    assert run.downloaded_frames == 3
    assert run.coverage == 1.0
    assert run.missing_timestamps == []
    assert [frame.frame_index for frame in run.frames] == [0, 1, 2]
    assert all(frame.validation_status == FrameValidationStatus.VALID for frame in run.frames)
    assert all(frame.sha256 and len(frame.sha256) == 64 for frame in run.frames)
    assert client.fetch_counts[START] == 1

    run_directory = tmp_path / "runs" / run.run_id
    assert sorted(path.name for path in (run_directory / "frames").iterdir()) == [
        "frame_000.jpg",
        "frame_001.jpg",
        "frame_002.jpg",
    ]
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "completed"
    assert manifest["canonical_timezone"] == "UTC"
    assert manifest["display_timezone"] == "Europe/Warsaw"
    assert manifest["downloaded_frames"] == 3
    assert len(manifest["frames"]) == 3  # type: ignore[arg-type]
    assert list(run_directory.glob(".manifest.*.tmp")) == []


@pytest.mark.asyncio
async def test_ingestion_persists_run_and_frame_metadata_to_database(tmp_path: Path) -> None:
    database = Database(tmp_path / "state" / "app.db")
    database.initialize()
    repository = ForecastRepository(database)
    service = create_service(tmp_path, FakeImgwClient(), repository=repository)

    run = await service.ingest(start_time=START, now=START)

    persisted = repository.get_run(run.run_id)
    assert persisted == run
    assert persisted is not None
    assert [frame.frame_index for frame in persisted.frames] == [0, 1, 2]


@pytest.mark.asyncio
async def test_explicit_start_uses_strict_missing_frame_policy(tmp_path: Path) -> None:
    missing_time = START + timedelta(minutes=30)
    client = FakeImgwClient(missing={missing_time})
    service = create_service(tmp_path, client)

    run = await service.ingest(start_time=START, now=START)

    assert run.status == ForecastRunStatus.FAILED
    assert run.downloaded_frames == 2
    assert run.missing_timestamps == [missing_time]
    assert "2026-08-29T10:30:00Z" in (run.error or "")
    assert run.frames[1].validation_status == FrameValidationStatus.MISSING
    assert not (tmp_path / "runs" / run.run_id / "frames" / "frame_001.jpg").exists()
    assert (tmp_path / "runs" / run.run_id / "frames" / "frame_000.jpg").is_file()
    assert (tmp_path / "runs" / run.run_id / "frames" / "frame_002.jpg").is_file()


@pytest.mark.asyncio
async def test_permissive_policy_completes_when_coverage_is_sufficient(tmp_path: Path) -> None:
    missing_time = START + timedelta(minutes=30)
    client = FakeImgwClient(missing={missing_time})
    service = create_service(
        tmp_path,
        client,
        allow_missing_frames=True,
        minimum_frame_coverage=0.66,
    )

    run = await service.ingest(start_time=START, now=START)

    assert run.status == ForecastRunStatus.COMPLETED
    assert run.downloaded_frames == 2
    assert run.coverage == pytest.approx(2 / 3)
    assert run.missing_timestamps == [missing_time]
    assert run.error is None


@pytest.mark.asyncio
async def test_permissive_policy_fails_below_minimum_coverage(tmp_path: Path) -> None:
    missing_time = START + timedelta(minutes=30)
    client = FakeImgwClient(missing={missing_time})
    service = create_service(
        tmp_path,
        client,
        allow_missing_frames=True,
        minimum_frame_coverage=0.70,
    )

    run = await service.ingest(start_time=START, now=START)

    assert run.status == ForecastRunStatus.FAILED
    assert "below required" in (run.error or "")


@pytest.mark.asyncio
async def test_validation_failure_is_never_hidden_by_permissive_mode(tmp_path: Path) -> None:
    invalid_time = START + timedelta(minutes=30)
    client = FakeImgwClient(invalid={invalid_time})
    service = create_service(
        tmp_path,
        client,
        allow_missing_frames=True,
        minimum_frame_coverage=0.50,
    )

    run = await service.ingest(start_time=START, now=START)

    assert run.status == ForecastRunStatus.FAILED
    assert run.frames[1].validation_status == FrameValidationStatus.FAILED
    assert "retrieval or persistence failed" in (run.error or "")


@pytest.mark.asyncio
async def test_latest_start_fallback_does_not_shift_later_sequence_times(tmp_path: Path) -> None:
    client = FakeImgwClient(missing_once={START})
    service = create_service(tmp_path, client)

    run = await service.ingest(now=START + timedelta(minutes=7))

    assert run.status == ForecastRunStatus.COMPLETED
    assert run.requested_start_time == START
    assert run.resolved_start_time == START - timedelta(minutes=30)
    assert [frame.forecast_time for frame in run.frames] == [
        START - timedelta(minutes=30),
        START,
        START + timedelta(minutes=30),
    ]
    assert client.fetch_counts[START] == 2


@pytest.mark.asyncio
async def test_ingestion_reuses_prevalidated_scheduler_boundary_frames(tmp_path: Path) -> None:
    client = FakeImgwClient()
    service = create_service(tmp_path, client)
    end = START + timedelta(hours=1)
    prefetched = {
        START: await client.fetch_frame(START),
        end: await client.fetch_frame(end),
    }
    probe = CompleteSequenceProbe(
        expected_start_time=START,
        resolved_start_time=START,
        fallback_steps=0,
        attempted_start_times=(START,),
        prefetched_frames=prefetched,
    )

    run = await service.ingest(now=START, latest_probe=probe)

    assert run.status == ForecastRunStatus.COMPLETED
    assert client.fetch_counts[START] == 1
    assert client.fetch_counts[end] == 1
    assert client.fetch_counts[START + timedelta(minutes=30)] == 1


@pytest.mark.asyncio
async def test_probe_failure_is_persisted_as_failed_run(tmp_path: Path) -> None:
    candidates = {
        START,
        START - timedelta(minutes=30),
        START - timedelta(minutes=60),
    }
    client = FakeImgwClient(missing=candidates)
    service = create_service(tmp_path, client, max_start_fallback_steps=2)

    run = await service.ingest(now=START + timedelta(minutes=7))

    assert run.status == ForecastRunStatus.FAILED
    assert run.resolved_start_time is None
    assert run.expected_frames == 0
    assert "No IMGW MERGE start frame found" in (run.error or "")
    assert read_manifest(tmp_path)["status"] == "failed"


@pytest.mark.asyncio
async def test_unsafe_generated_run_id_is_rejected_before_writing(tmp_path: Path) -> None:
    client = FakeImgwClient()
    service = create_service(tmp_path, client, run_id="../../outside")

    with pytest.raises(ValueError, match="Unsafe forecast run ID"):
        await service.ingest(start_time=START, now=START)

    assert not (tmp_path.parent / "outside").exists()
