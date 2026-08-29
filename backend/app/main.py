"""FastAPI entry point for imgw-merge-weather."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.config import Settings, get_settings


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ServiceStatusResponse(BaseModel):
    service: str
    version: str
    milestone: int
    weather_data_available: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_settings.ensure_data_directories()
        yield

    application = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=app_settings.app_name,
            version=__version__,
        )

    @application.get("/api/status", response_model=ServiceStatusResponse, tags=["operations"])
    async def service_status() -> ServiceStatusResponse:
        return ServiceStatusResponse(
            service=app_settings.app_name,
            version=__version__,
            milestone=1,
            weather_data_available=False,
        )

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
