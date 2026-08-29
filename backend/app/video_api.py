"""Video generation REST API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse

from app.database import ForecastRepository, VideoRepository
from app.models import VideoGenerationStatus
from app.schemas import (
    VideoCreateRequest,
    VideoGenerationListResponse,
    VideoGenerationResponse,
    video_generation_response,
)
from app.services.ingestion import RUN_ID_PATTERN
from app.services.video_generation import (
    VideoGenerationConflictError,
    VideoGenerationCoordinator,
)
from app.video import VideoGenerationError, resolve_video_output_path

router = APIRouter(tags=["videos"])
RunId = Annotated[str, ApiPath(pattern=RUN_ID_PATTERN.pattern)]
VideoId = Annotated[str, ApiPath(pattern=r"^video_[a-z0-9]{8,64}$")]


def _forecast_repository(request: Request) -> ForecastRepository:
    repository = getattr(request.app.state, "forecast_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Forecast persistence is unavailable")
    return repository


def _video_repository(request: Request) -> VideoRepository:
    repository = getattr(request.app.state, "video_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Video persistence is unavailable")
    return repository


def _coordinator(request: Request) -> VideoGenerationCoordinator:
    coordinator = getattr(request.app.state, "video_coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Video generation is unavailable")
    return coordinator


@router.get("/api/videos", response_model=VideoGenerationListResponse)
async def list_videos(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    run_id: Annotated[str | None, Query(pattern=RUN_ID_PATTERN.pattern)] = None,
) -> VideoGenerationListResponse:
    videos = _video_repository(request).list(limit=limit, run_id=run_id)
    return VideoGenerationListResponse(
        videos=[video_generation_response(video) for video in videos],
        count=len(videos),
    )


@router.get("/api/videos/{video_id}", response_model=VideoGenerationResponse)
async def video_detail(request: Request, video_id: VideoId) -> VideoGenerationResponse:
    video = _video_repository(request).get(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video generation not found")
    return video_generation_response(video)


@router.post(
    "/api/runs/{run_id}/videos",
    response_model=VideoGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_video(
    request: Request,
    run_id: RunId,
    payload: VideoCreateRequest,
) -> VideoGenerationResponse:
    if _forecast_repository(request).get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Forecast run not found")
    try:
        video = await _coordinator(request).start(
            run_id=run_id,
            mode=payload.mode,
            fps=payload.fps,
        )
    except VideoGenerationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except VideoGenerationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return video_generation_response(video)


@router.get("/api/videos/{video_id}/file", response_class=FileResponse)
async def video_file(request: Request, video_id: VideoId) -> FileResponse:
    video = _video_repository(request).get(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video generation not found")
    if video.status != VideoGenerationStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Video generation is not completed")
    try:
        output_path = resolve_video_output_path(
            request.app.state.settings.output_dir, video.output_filename
        )
    except VideoGenerationError as error:
        raise HTTPException(status_code=404, detail="Video file is unavailable") from error
    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Video file is unavailable")
    return FileResponse(
        output_path,
        media_type="video/mp4",
        headers={"Cache-Control": "private, max-age=3600"},
    )
