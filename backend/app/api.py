"""Forecast REST API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse

from app.config import Settings
from app.database import ForecastRepository
from app.models import ForecastFrame, ForecastRun, FrameValidationStatus
from app.schemas import (
    ForecastRunDetailResponse,
    ForecastRunListResponse,
    RefreshAcceptedResponse,
    forecast_run_detail,
    forecast_run_summary,
)
from app.services.ingestion import RUN_ID_PATTERN
from app.services.refresh import RefreshCoordinator

router = APIRouter(prefix="/api/runs", tags=["forecast runs"])
RunId = Annotated[str, ApiPath(pattern=RUN_ID_PATTERN.pattern)]
FrameIndex = Annotated[int, ApiPath(ge=0, le=10_000)]


def _repository(request: Request) -> ForecastRepository:
    repository = getattr(request.app.state, "forecast_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Forecast persistence is unavailable")
    return repository


def _refresh_coordinator(request: Request) -> RefreshCoordinator:
    coordinator = getattr(request.app.state, "refresh_coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Forecast refresh is unavailable")
    return coordinator


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("", response_model=ForecastRunListResponse)
async def list_forecast_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ForecastRunListResponse:
    repository = _repository(request)
    runs = repository.list_runs(limit=limit)
    latest = repository.get_latest_completed_run()
    now = datetime.now(UTC)
    return ForecastRunListResponse(
        runs=[forecast_run_summary(run, now=now) for run in runs],
        count=len(runs),
        latest_run_id=latest.run_id if latest is not None else None,
    )


@router.get("/latest", response_model=ForecastRunDetailResponse)
async def latest_forecast_run(request: Request) -> ForecastRunDetailResponse:
    run = _repository(request).get_latest_completed_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No completed forecast run is available")
    return forecast_run_detail(run)


@router.post(
    "/refresh",
    response_model=RefreshAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_forecast_run(request: Request) -> RefreshAcceptedResponse:
    coordinator = _refresh_coordinator(request)
    if not await coordinator.start():
        raise HTTPException(status_code=409, detail="A forecast refresh is already running")
    return RefreshAcceptedResponse(
        status="accepted",
        detail="Forecast refresh started; poll /api/runs for progress",
    )


@router.get("/{run_id}", response_model=ForecastRunDetailResponse)
async def forecast_run_detail_by_id(
    request: Request,
    run_id: RunId,
) -> ForecastRunDetailResponse:
    run = _repository(request).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Forecast run not found")
    return forecast_run_detail(run)


@router.get("/{run_id}/frames/{frame_index}", response_class=FileResponse)
async def forecast_frame_file(
    request: Request,
    run_id: RunId,
    frame_index: FrameIndex,
) -> FileResponse:
    run = _repository(request).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Forecast run not found")
    frame = next((item for item in run.frames if item.frame_index == frame_index), None)
    if frame is None or frame.validation_status != FrameValidationStatus.VALID:
        raise HTTPException(status_code=404, detail="Forecast frame is not available")

    frame_path = resolve_frame_path(_settings(request).runs_dir, run, frame)
    if not frame_path.is_file():
        raise HTTPException(status_code=404, detail="Forecast frame file is not available")
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Forecast-Time": frame.forecast_time.isoformat().replace("+00:00", "Z"),
        "X-Frame-Index": str(frame.frame_index),
    }
    if frame.sha256 is not None:
        headers["ETag"] = f'"{frame.sha256}"'
    return FileResponse(frame_path, media_type="image/jpeg", headers=headers)


def resolve_frame_path(
    runs_directory: Path,
    run: ForecastRun,
    frame: ForecastFrame,
) -> Path:
    """Resolve only metadata paths contained by the matching immutable run directory."""

    runs_root = runs_directory.resolve()
    run_directory = (runs_root / run.run_id).resolve()
    frames_directory = (run_directory / "frames").resolve()
    frame_path = (run_directory / frame.local_filename).resolve()
    if run_directory.parent != runs_root or not frame_path.is_relative_to(frames_directory):
        raise HTTPException(status_code=404, detail="Forecast frame file is not available")
    return frame_path
