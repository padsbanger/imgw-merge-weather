"""Stable REST DTOs kept separate from persistence and frontend component state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.freshness import FreshnessState, calculate_forecast_freshness
from app.models import (
    ForecastRun,
    ForecastRunStatus,
    FrameValidationStatus,
    VideoGeneration,
    VideoGenerationStatus,
    VideoMode,
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class SchedulerStatusResponse(BaseModel):
    enabled: bool
    state: str
    next_run_at: datetime | None


class ServiceStatusResponse(BaseModel):
    service: str
    version: str
    milestone: int
    server_time: datetime
    weather_data_available: bool
    refresh_in_progress: bool
    last_refresh_at: datetime | None
    last_refresh_status: str | None
    last_imgw_error: str | None
    scheduler: SchedulerStatusResponse


class FreshnessResponse(BaseModel):
    state: FreshnessState
    reference_time: datetime
    age_seconds: int = Field(ge=0)


class RunProgressResponse(BaseModel):
    downloaded_frames: int = Field(ge=0)
    expected_frames: int = Field(ge=0)
    fraction: float = Field(ge=0, le=1)


class ForecastFrameResponse(BaseModel):
    frame_index: int = Field(ge=0)
    forecast_time: datetime
    frame_url: str
    source_url: str
    width: int | None
    height: int | None
    size_bytes: int | None
    sha256: str | None
    validation_status: FrameValidationStatus
    error: str | None


class ForecastRunSummaryResponse(BaseModel):
    run_id: str
    discovered_at: datetime
    updated_at: datetime
    source: str
    product: str
    canonical_timezone: str
    display_timezone: str
    requested_start_time: datetime
    resolved_start_time: datetime | None
    forecast_end_time: datetime | None
    interval_minutes: int
    forecast_hours: int
    status: ForecastRunStatus
    progress: RunProgressResponse
    coverage: float
    missing_timestamps: list[datetime]
    error: str | None
    freshness: FreshnessResponse
    detail_url: str


class ForecastRunDetailResponse(ForecastRunSummaryResponse):
    frames: list[ForecastFrameResponse]


class ForecastRunListResponse(BaseModel):
    runs: list[ForecastRunSummaryResponse]
    count: int = Field(ge=0)
    latest_run_id: str | None


class RefreshAcceptedResponse(BaseModel):
    status: str
    detail: str


class VideoCreateRequest(BaseModel):
    mode: VideoMode = VideoMode.SOURCE
    fps: int | None = Field(default=None, ge=1, le=30)


class VideoGenerationResponse(BaseModel):
    video_id: str
    run_id: str
    created_at: datetime
    updated_at: datetime
    status: VideoGenerationStatus
    mode: VideoMode
    fps: int
    codec: str
    crf: int
    preset: str
    output_filename: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    size_bytes: int | None
    error: str | None
    detail_url: str
    file_url: str | None


class VideoGenerationListResponse(BaseModel):
    videos: list[VideoGenerationResponse]
    count: int = Field(ge=0)


def forecast_run_summary(
    run: ForecastRun,
    *,
    now: datetime | None = None,
) -> ForecastRunSummaryResponse:
    freshness = calculate_forecast_freshness(run, now=now)
    return ForecastRunSummaryResponse(
        run_id=run.run_id,
        discovered_at=run.discovered_at,
        updated_at=run.updated_at,
        source=run.source,
        product=run.product,
        canonical_timezone=run.canonical_timezone,
        display_timezone=run.display_timezone,
        requested_start_time=run.requested_start_time,
        resolved_start_time=run.resolved_start_time,
        forecast_end_time=run.forecast_end_time,
        interval_minutes=run.interval_minutes,
        forecast_hours=run.forecast_hours,
        status=run.status,
        progress=RunProgressResponse(
            downloaded_frames=run.downloaded_frames,
            expected_frames=run.expected_frames,
            fraction=run.coverage,
        ),
        coverage=run.coverage,
        missing_timestamps=run.missing_timestamps,
        error=run.error,
        freshness=FreshnessResponse(
            state=freshness.state,
            reference_time=freshness.reference_time,
            age_seconds=freshness.age_seconds,
        ),
        detail_url=f"/api/runs/{run.run_id}",
    )


def forecast_run_detail(
    run: ForecastRun,
    *,
    now: datetime | None = None,
) -> ForecastRunDetailResponse:
    summary = forecast_run_summary(run, now=now)
    return ForecastRunDetailResponse(
        **summary.model_dump(),
        frames=[
            ForecastFrameResponse(
                frame_index=frame.frame_index,
                forecast_time=frame.forecast_time,
                frame_url=f"/api/runs/{run.run_id}/frames/{frame.frame_index}",
                source_url=frame.source_url,
                width=frame.width,
                height=frame.height,
                size_bytes=frame.size_bytes,
                sha256=frame.sha256,
                validation_status=frame.validation_status,
                error=frame.error,
            )
            for frame in run.frames
        ],
    )


def video_generation_response(video: VideoGeneration) -> VideoGenerationResponse:
    completed = video.status == VideoGenerationStatus.COMPLETED
    return VideoGenerationResponse(
        **video.model_dump(),
        detail_url=f"/api/videos/{video.video_id}",
        file_url=f"/api/videos/{video.video_id}/file" if completed else None,
    )
