from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.imgw_client import (
    DEFAULT_HEADERS,
    FrameRequestError,
    FrameValidationError,
    ImgwMergeClient,
    build_frame_filename,
    build_frame_url,
    format_frame_timestamp,
)

FRAME_TIME = datetime(2026, 8, 29, 12, 50, tzinfo=UTC)
BASE_URL = "https://cmm.imgw.pl/wp-content/uploads/production/MERGE"
EXPECTED_FILENAME = "MERGE_MERGE_10_2026-08-29_12_50_00.jpg"
EXPECTED_URL = f"{BASE_URL}/{EXPECTED_FILENAME}"


def make_jpeg(size: tuple[int, int] = (320, 180)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=(25, 35, 45)).save(output, format="JPEG", quality=90)
    return output.getvalue()


def make_http_client(handler: httpx.AsyncBaseTransport | httpx.BaseTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def test_timestamp_and_filename_formatting_are_exact() -> None:
    assert format_frame_timestamp(FRAME_TIME) == "2026-08-29_12_50_00"
    assert build_frame_filename(FRAME_TIME) == EXPECTED_FILENAME


def test_filename_converts_an_aware_local_time_to_verified_utc() -> None:
    warsaw_summer_offset = timezone(timedelta(hours=2))
    local_time = datetime(2026, 8, 29, 14, 50, tzinfo=warsaw_summer_offset)

    assert format_frame_timestamp(local_time) == "2026-08-29_12_50_00"
    assert build_frame_filename(local_time) == EXPECTED_FILENAME


def test_timestamp_formatting_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_frame_timestamp(datetime(2026, 8, 29, 12, 50))


def test_build_frame_url_handles_trailing_slash() -> None:
    assert build_frame_url(f"{BASE_URL}/", FRAME_TIME) == EXPECTED_URL


@pytest.mark.asyncio
async def test_fetches_valid_jpeg_with_browser_compatible_headers() -> None:
    jpeg = make_jpeg()
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, content=jpeg, headers={"Content-Type": "image/jpeg"})

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(base_url=BASE_URL, http_client=http_client, max_retries=0)
        frame = await client.fetch_frame(FRAME_TIME)

    assert frame.content == jpeg
    assert frame.metadata.source_url == EXPECTED_URL
    assert frame.metadata.forecast_time == FRAME_TIME
    assert frame.metadata.size_bytes == len(jpeg)
    assert (frame.metadata.width, frame.metadata.height) == (320, 180)
    assert frame.metadata.image_format == "JPEG"
    assert captured_request is not None
    assert captured_request.headers["user-agent"] == DEFAULT_HEADERS["User-Agent"]
    assert captured_request.headers["accept"] == DEFAULT_HEADERS["Accept"]
    assert captured_request.headers["referer"] == DEFAULT_HEADERS["Referer"]


@pytest.mark.asyncio
async def test_rejects_corrupt_jpeg() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-a-jpeg" * 200,
            headers={"Content-Type": "image/jpeg"},
        )

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(base_url=BASE_URL, http_client=http_client, max_retries=0)
        with pytest.raises(FrameValidationError, match="not a decodable image"):
            await client.fetch_frame(FRAME_TIME)


@pytest.mark.asyncio
async def test_rejects_html_response_with_http_200() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body>temporarily unavailable</body></html>" * 30,
            headers={"Content-Type": "text/html; charset=UTF-8"},
        )

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(base_url=BASE_URL, http_client=http_client, max_retries=0)
        with pytest.raises(FrameValidationError, match="unexpected content type"):
            await client.fetch_frame(FRAME_TIME)


@pytest.mark.asyncio
async def test_rejects_empty_response() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"Content-Type": "image/jpeg"})

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(base_url=BASE_URL, http_client=http_client, max_retries=0)
        with pytest.raises(FrameValidationError, match="too small"):
            await client.fetch_frame(FRAME_TIME)


@pytest.mark.asyncio
async def test_timeout_retries_with_exponential_backoff_then_succeeds() -> None:
    jpeg = make_jpeg()
    attempts = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("IMGW read timed out", request=request)
        return httpx.Response(200, content=jpeg, headers={"Content-Type": "image/jpeg"})

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(
            base_url=BASE_URL,
            http_client=http_client,
            max_retries=2,
            backoff_seconds=0.25,
            sleep=record_sleep,
        )
        frame = await client.fetch_frame(FRAME_TIME)

    assert frame.metadata.image_format == "JPEG"
    assert attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_timeout_exhaustion_raises_informative_error() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("IMGW connect timed out", request=request)

    async def no_sleep(_: float) -> None:
        return None

    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(
            base_url=BASE_URL,
            http_client=http_client,
            max_retries=2,
            backoff_seconds=0,
            sleep=no_sleep,
        )
        with pytest.raises(FrameRequestError, match="after 3 attempts"):
            await client.fetch_frame(FRAME_TIME)

    assert attempts == 3


@pytest.mark.asyncio
async def test_download_writes_validated_frame_atomically(tmp_path: Path) -> None:
    jpeg = make_jpeg()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg, headers={"Content-Type": "image/jpeg"})

    destination = tmp_path / "frames" / "frame_000.jpg"
    async with make_http_client(httpx.MockTransport(handler)) as http_client:
        client = ImgwMergeClient(base_url=BASE_URL, http_client=http_client, max_retries=0)
        metadata = await client.download_frame(FRAME_TIME, destination)

    assert destination.read_bytes() == jpeg
    assert metadata.size_bytes == len(jpeg)
    assert list(destination.parent.glob("*.tmp")) == []
    assert list(destination.parent.glob(".*.tmp")) == []
