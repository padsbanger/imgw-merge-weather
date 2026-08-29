"""Filesystem-era domain models for forecast runs and frames."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.forecast import to_utc


class ForecastRunStatus(StrEnum):
    PENDING = "pending"
    PROBING = "probing"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class FrameValidationStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    MISSING = "missing"
    FAILED = "failed"


class VideoGenerationStatus(StrEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoMode(StrEnum):
    SOURCE = "source"
    SQUARE = "1:1"


class ForecastFrame(BaseModel):
    frame_index: int = Field(ge=0)
    forecast_time: datetime
    source_url: str
    local_filename: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    validation_status: FrameValidationStatus = FrameValidationStatus.PENDING
    error: str | None = None

    @field_validator("forecast_time")
    @classmethod
    def canonicalize_forecast_time(cls, timestamp: datetime) -> datetime:
        return to_utc(timestamp)


class ForecastRun(BaseModel):
    manifest_version: int = 1
    run_id: str
    discovered_at: datetime
    updated_at: datetime
    source: str = "IMGW CMM"
    product: str = "MERGE"
    canonical_timezone: str = "UTC"
    filename_timezone: str = "UTC"
    display_timezone: str = "Europe/Warsaw"
    requested_start_time: datetime
    resolved_start_time: datetime | None = None
    forecast_end_time: datetime | None = None
    interval_minutes: int = Field(gt=0)
    forecast_hours: int = Field(gt=0)
    expected_frames: int = Field(default=0, ge=0)
    downloaded_frames: int = Field(default=0, ge=0)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    allow_missing_frames: bool
    minimum_frame_coverage: float = Field(ge=0.0, le=1.0)
    status: ForecastRunStatus = ForecastRunStatus.PENDING
    missing_timestamps: list[datetime] = Field(default_factory=list)
    error: str | None = None
    frames: list[ForecastFrame] = Field(default_factory=list)

    @field_validator(
        "discovered_at",
        "updated_at",
        "requested_start_time",
        "resolved_start_time",
        "forecast_end_time",
    )
    @classmethod
    def canonicalize_timestamp(cls, timestamp: datetime | None) -> datetime | None:
        return to_utc(timestamp) if timestamp is not None else None

    @field_validator("missing_timestamps")
    @classmethod
    def canonicalize_missing_timestamps(cls, timestamps: list[datetime]) -> list[datetime]:
        return [to_utc(timestamp) for timestamp in timestamps]


class VideoGeneration(BaseModel):
    video_id: str = Field(pattern=r"^video_[a-z0-9]{8,64}$")
    run_id: str
    created_at: datetime
    updated_at: datetime
    status: VideoGenerationStatus = VideoGenerationStatus.PENDING
    mode: VideoMode
    fps: int = Field(ge=1, le=30)
    codec: str = "libx264"
    crf: int = Field(ge=0, le=51)
    preset: str
    output_filename: str
    start_frame_index: int = Field(default=0, ge=0)
    end_frame_index: int | None = Field(default=None, ge=0)
    timestamp_overlay: bool = False
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, ge=0)
    error: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def canonicalize_video_timestamp(cls, timestamp: datetime) -> datetime:
        return to_utc(timestamp)

    @field_validator("output_filename")
    @classmethod
    def validate_output_filename(cls, filename: str) -> str:
        if not filename or filename != filename.strip():
            raise ValueError("output filename must not be blank")
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError("output filename must be a basename")
        if not filename.endswith(".mp4"):
            raise ValueError("output filename must use the .mp4 extension")
        return filename
