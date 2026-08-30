"""Application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from IMGW-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="IMGW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "imgw-merge-weather"
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    static_dir: Path | None = None
    base_url: str = "https://cmm.imgw.pl/wp-content/uploads/production/MERGE"
    user_agent: str = "imgw-merge-weather/1.0 homelab-weather-viewer"
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    frame_concurrency: int = Field(default=4, ge=1, le=16)
    min_frame_bytes: int = Field(default=1_024, ge=1)
    min_frame_width: int = Field(default=100, ge=1)
    min_frame_height: int = Field(default=100, ge=1)
    frame_interval_minutes: int = Field(default=10, ge=1, le=60)
    forecast_hours: int = Field(default=8, ge=1, le=24)
    forecast_lookback_hours: int = Field(default=2, ge=0, le=6)
    max_start_fallback_steps: int = Field(default=6, ge=0, le=12)
    allow_missing_frames: bool = False
    min_frame_coverage: float = Field(default=0.90, ge=0.0, le=1.0)
    scheduler_enabled: bool = False
    scheduler_cron: str = "2 * * * *"
    scheduler_misfire_grace_seconds: int = Field(default=60, ge=1, le=600)
    video_source_fps: int = Field(default=3, ge=1, le=10)
    video_output_fps: int = Field(default=30, ge=15, le=60)
    video_interpolation: Literal["none", "crossfade"] = "crossfade"
    video_auto_generate: bool = False
    video_max_concurrent_renders: int = Field(default=1, ge=1, le=4)
    video_codec: Literal["libx264"] = "libx264"
    video_crf: int = Field(default=20, ge=0, le=51)
    video_preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = "medium"
    square_video_size: int = Field(default=1080, ge=240, le=2160, multiple_of=2)
    min_video_bytes: int = Field(default=1_024, ge=1)
    video_timeout_seconds: float = Field(default=300, gt=0, le=3_600)
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def database_path(self) -> Path:
        return self.state_dir / "app.db"

    def ensure_data_directories(self) -> None:
        """Create only the known application data directories."""

        for path in (self.runs_dir, self.output_dir, self.state_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
