"""Rate-conscious client for individual IMGW CMM MERGE JPEG frames."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from app.forecast import to_utc

LOGGER = logging.getLogger(__name__)

FRAME_TIMESTAMP_FORMAT = "%Y-%m-%d_%H_%M_%S"
FRAME_FILENAME_PREFIX = "MERGE_MERGE_10_"
DEFAULT_HEADERS = {
    "User-Agent": "imgw-merge-weather/1.0 homelab-weather-viewer",
    "Accept": "image/avif,image/webp,image/apng,image/jpeg,*/*",
    "Referer": "https://cmm.imgw.pl/",
}
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
JPEG_CONTENT_TYPES = frozenset({"image/jpeg", "image/jpg", "image/pjpeg"})


class ImgwClientError(RuntimeError):
    """Base error raised by the IMGW client."""


class FrameUnavailableError(ImgwClientError):
    """The requested frame was not returned with HTTP 200."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"IMGW frame request returned HTTP {status_code}: {url}")
        self.url = url
        self.status_code = status_code


class FrameValidationError(ImgwClientError):
    """The response body was not a valid MERGE JPEG frame."""


class FrameRequestError(ImgwClientError):
    """The request failed after the configured retry budget."""


@dataclass(frozen=True, slots=True)
class FrameMetadata:
    forecast_time: datetime
    source_url: str
    content_type: str | None
    size_bytes: int
    width: int
    height: int
    image_format: str


@dataclass(frozen=True, slots=True)
class DownloadedFrame:
    metadata: FrameMetadata
    content: bytes


@dataclass(frozen=True, slots=True)
class ImageDimensions:
    width: int
    height: int
    image_format: str


def format_frame_timestamp(timestamp: datetime) -> str:
    """Format a forecast valid time using IMGW's verified UTC convention."""

    return to_utc(timestamp).strftime(FRAME_TIMESTAMP_FORMAT)


def build_frame_filename(timestamp: datetime) -> str:
    return f"{FRAME_FILENAME_PREFIX}{format_frame_timestamp(timestamp)}.jpg"


def build_frame_url(base_url: str, timestamp: datetime) -> str:
    if not base_url.strip():
        raise ValueError("IMGW base URL must not be empty")
    return f"{base_url.rstrip('/')}/{build_frame_filename(timestamp)}"


def validate_frame_body(
    content: bytes,
    content_type: str | None,
    *,
    min_body_size: int = 1_024,
    min_width: int = 100,
    min_height: int = 100,
) -> ImageDimensions:
    """Decode and verify that a response body is a sensible JPEG weather frame."""

    if len(content) < min_body_size:
        raise FrameValidationError(
            f"IMGW frame body is too small: {len(content)} bytes (minimum {min_body_size})"
        )

    normalized_content_type = (
        content_type.split(";", 1)[0].strip().lower() if content_type else None
    )
    if normalized_content_type and normalized_content_type not in JPEG_CONTENT_TYPES:
        raise FrameValidationError(
            f"IMGW frame has unexpected content type: {normalized_content_type}"
        )

    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
            image_format = image.format

        with Image.open(BytesIO(content)) as decoded_image:
            width, height = decoded_image.size
            decoded_image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise FrameValidationError("IMGW frame body is not a decodable image") from error

    if image_format != "JPEG":
        raise FrameValidationError(f"IMGW frame has unexpected image format: {image_format}")
    if width < min_width or height < min_height:
        raise FrameValidationError(
            "IMGW frame dimensions are too small: "
            f"{width}x{height} (minimum {min_width}x{min_height})"
        )

    return ImageDimensions(width=width, height=height, image_format=image_format)


class ImgwMergeClient:
    """Asynchronous, bounded client for fetching and validating MERGE frames."""

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str = DEFAULT_HEADERS["User-Agent"],
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 20.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        concurrency: int = 4,
        min_body_size: int = 1_024,
        min_width: int = 100,
        min_height: int = 100,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("IMGW base URL must not be empty")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")

        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_body_size = min_body_size
        self.min_width = min_width
        self.min_height = min_height
        self._semaphore = asyncio.Semaphore(concurrency)
        self._sleep = sleep
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=read_timeout_seconds,
                connect=connect_timeout_seconds,
            ),
            follow_redirects=True,
        )
        self._headers = {**DEFAULT_HEADERS, "User-Agent": user_agent}

    async def __aenter__(self) -> ImgwMergeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    def frame_url(self, timestamp: datetime) -> str:
        return build_frame_url(self.base_url, timestamp)

    async def fetch_frame(self, timestamp: datetime) -> DownloadedFrame:
        """GET and validate exactly one frame, retrying bounded transient failures."""

        canonical_time = to_utc(timestamp)
        url = self.frame_url(canonical_time)
        async with self._semaphore:
            return await self._fetch_with_retries(canonical_time, url)

    async def download_frame(self, timestamp: datetime, destination: Path) -> FrameMetadata:
        """Fetch one frame and atomically replace the destination after validation."""

        frame = await self.fetch_frame(timestamp)
        await asyncio.to_thread(_atomic_write, destination, frame.content)
        LOGGER.info(
            "event=frame_download forecast_time=%s status=success size_bytes=%d path=%s",
            frame.metadata.forecast_time.isoformat(),
            frame.metadata.size_bytes,
            destination,
        )
        return frame.metadata

    async def save_frame(self, frame: DownloadedFrame, destination: Path) -> FrameMetadata:
        """Atomically save an already fetched and validated frame without another GET."""

        await asyncio.to_thread(_atomic_write, destination, frame.content)
        LOGGER.info(
            "event=frame_save forecast_time=%s status=success size_bytes=%d path=%s",
            frame.metadata.forecast_time.isoformat(),
            frame.metadata.size_bytes,
            destination,
        )
        return frame.metadata

    async def _fetch_with_retries(self, timestamp: datetime, url: str) -> DownloadedFrame:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http_client.get(url, headers=self._headers)
                if response.status_code != httpx.codes.OK:
                    raise FrameUnavailableError(url, response.status_code)

                dimensions = validate_frame_body(
                    response.content,
                    response.headers.get("content-type"),
                    min_body_size=self.min_body_size,
                    min_width=self.min_width,
                    min_height=self.min_height,
                )
                metadata = FrameMetadata(
                    forecast_time=timestamp,
                    source_url=url,
                    content_type=response.headers.get("content-type"),
                    size_bytes=len(response.content),
                    width=dimensions.width,
                    height=dimensions.height,
                    image_format=dimensions.image_format,
                )
                return DownloadedFrame(metadata=metadata, content=response.content)
            except FrameUnavailableError as error:
                if error.status_code not in RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                    raise
                await self._retry_delay(attempt, url, f"HTTP {error.status_code}")
            except FrameValidationError:
                if attempt >= self.max_retries:
                    raise
                await self._retry_delay(attempt, url, "invalid image body")
            except httpx.TimeoutException as error:
                if attempt >= self.max_retries:
                    raise FrameRequestError(
                        f"IMGW frame request timed out after {attempt + 1} attempts: {url}"
                    ) from error
                await self._retry_delay(attempt, url, "timeout")
            except httpx.RequestError as error:
                if attempt >= self.max_retries:
                    raise FrameRequestError(
                        f"IMGW frame request failed after {attempt + 1} attempts: {url}"
                    ) from error
                await self._retry_delay(attempt, url, error.__class__.__name__)

        raise AssertionError("unreachable retry state")

    async def _retry_delay(self, attempt: int, url: str, reason: str) -> None:
        delay = self.backoff_seconds * (2**attempt)
        LOGGER.warning(
            "event=frame_fetch_retry url=%s attempt=%d delay_seconds=%.2f reason=%s",
            url,
            attempt + 1,
            delay,
            reason,
        )
        await self._sleep(delay)


def _atomic_write(destination: Path, content: bytes) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
