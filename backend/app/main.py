"""FastAPI entry point for imgw-merge-weather."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router as forecast_router
from app.config import Settings, get_settings
from app.database import ForecastRepository, VideoRepository
from app.persistence import initialize_forecast_persistence
from app.schemas import HealthResponse, SchedulerStatusResponse, ServiceStatusResponse
from app.services.refresh import RefreshCoordinator, ingest_latest_forecast
from app.services.video_generation import VideoGenerationCoordinator
from app.video import VideoGenerationService
from app.video_api import router as video_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    repository: ForecastRepository | None = None
    refresh_coordinator: RefreshCoordinator | None = None
    video_coordinator: VideoGenerationCoordinator | None = None

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI) -> AsyncIterator[None]:
        nonlocal refresh_coordinator, repository, video_coordinator
        app_settings.ensure_data_directories()
        repository, _ = initialize_forecast_persistence(
            database_path=app_settings.database_path,
            runs_directory=app_settings.runs_dir,
        )
        refresh_coordinator = RefreshCoordinator(
            lambda: ingest_latest_forecast(app_settings, repository),
            repository=repository,
        )
        video_repository = VideoRepository(repository.database)
        video_repository.recover_interrupted()
        video_service = VideoGenerationService(
            settings=app_settings,
            forecast_repository=repository,
            video_repository=video_repository,
        )
        video_coordinator = VideoGenerationCoordinator(
            service=video_service,
            repository=video_repository,
        )
        lifespan_app.state.forecast_repository = repository
        lifespan_app.state.refresh_coordinator = refresh_coordinator
        lifespan_app.state.video_repository = video_repository
        lifespan_app.state.video_coordinator = video_coordinator
        try:
            yield
        finally:
            await video_coordinator.shutdown()
            await refresh_coordinator.shutdown()

    application = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = app_settings

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=app_settings.app_name,
            version=__version__,
        )

    @application.get("/api/status", response_model=ServiceStatusResponse, tags=["operations"])
    async def service_status(request: Request) -> ServiceStatusResponse:
        coordinator = getattr(request.app.state, "refresh_coordinator", None)
        return ServiceStatusResponse(
            service=app_settings.app_name,
            version=__version__,
            milestone=9,
            server_time=datetime.now(UTC),
            weather_data_available=(
                repository.has_completed_run() if repository is not None else False
            ),
            refresh_in_progress=(coordinator.is_running if coordinator is not None else False),
            last_refresh_at=(coordinator.last_refresh_at if coordinator is not None else None),
            last_refresh_status=(
                coordinator.last_refresh_status if coordinator is not None else None
            ),
            last_imgw_error=(coordinator.last_imgw_error if coordinator is not None else None),
            scheduler=SchedulerStatusResponse(
                enabled=app_settings.scheduler_enabled,
                state="not_configured" if app_settings.scheduler_enabled else "disabled",
                next_run_at=None,
            ),
        )

    application.include_router(forecast_router)
    application.include_router(video_router)
    register_frontend(application, app_settings.static_dir)
    return application


def register_frontend(application: FastAPI, static_dir: Path | None) -> None:
    """Serve a built Vite app without allowing SPA fallback to consume API paths."""

    if static_dir is None or not (static_dir / "index.html").is_file():
        return

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @application.get("/{path:path}", include_in_schema=False)
    async def frontend_fallback(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/") or path == "health":
            raise HTTPException(status_code=404, detail="Not found")

        requested_file = static_dir / path
        if requested_file.is_file() and requested_file.is_relative_to(static_dir):
            return FileResponse(requested_file)
        return FileResponse(static_dir / "index.html")


app = create_app()
