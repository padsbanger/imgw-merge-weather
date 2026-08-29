"""Application configuration."""

from functools import lru_cache
from pathlib import Path

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
    log_level: str = "info"
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

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    def ensure_data_directories(self) -> None:
        """Create only the known application data directories."""

        for path in (self.runs_dir, self.output_dir, self.state_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
