# imgw-merge-weather

Self-hosted weather viewer for collecting IMGW CMM MERGE precipitation forecast frames,
exploring forecast runs, and generating shareable MP4 animations.

**Milestones 0–11 are complete.** The repository provides a typed FastAPI backend, an
interactive React weather viewer with explicit live-data freshness and forecast-run
history, validated IMGW MERGE frame retrieval, canonical UTC forecast sequencing,
complete run ingestion, SQLite metadata persistence, validated FFmpeg MP4 generation,
an integrated video drawer, optional duplicate-safe automatic refresh, automated tests
and linting, and a single-container Docker Compose deployment.

## Quick start with Docker

```bash
cp .env.example .env
docker compose build
docker compose up -d
curl http://localhost:8080/health
```

Open <http://localhost:8080>. Runtime files are persisted under `./data`.

The root page opens the latest forecast immediately. Use the timeline or its range
control to select a timestamp, the compact controls to move or play/pause, and the run
panel to inspect recent forecast snapshots. Frames play in a loop at 2 FPS. Local Warsaw
time is displayed prominently while UTC remains visible for source traceability.

Selecting another publication preserves the current forecast offset when possible. If
that exact timestamp is missing, the nearest valid frame is selected. Latest and
historical runs are explicitly labeled; partial and failed ingestion attempts remain in
the run browser with progress, missing-frame counts, source UTC timestamps, and the
recorded failure reason. The viewer never fills a gap with a different weather frame.

The header continuously shows Warsaw local time and one of `LIVE`, `FRESH`, `DELAYED`,
`STALE`, or `OFFLINE`. The run panel shows source update time, data age, backend
reachability, refresh activity, last refresh outcome, any last IMGW error, and scheduler
state. Cached imagery remains visible during a backend outage but is explicitly marked
`OFFLINE`.

Use the compact `Generate video` action in the current-run panel to open the secondary
video drawer. Choose a forecast frame range, 1–30 FPS, source or padded 1080×1080 output,
and optionally add a Warsaw/UTC timestamp overlay. The drawer tracks active rendering,
plays completed MP4s with native browser controls, and provides download, metadata, and
confirmation-protected deletion while leaving the weather map as the primary workspace.

### Local network access

Compose publishes the application on all host interfaces by default. Open it from
another device on the same network using the server's LAN address:

```text
http://HOMELAB_IP:8080
```

Set `APP_PORT` in `.env` when port 8080 is already occupied. Set
`APP_BIND_ADDRESS=127.0.0.1` only when the application should not be reachable directly
from the local network.

The runtime user defaults to UID/GID 1000 so it can write to a normal homelab user's
bind-mounted `./data` directory while the application process remains non-root. Override
`APP_UID` and `APP_GID` in `.env` when the directory owner uses different numeric IDs.

## Local development

Requirements:

- Python 3.12+
- Node.js 22+

Install dependencies:

```bash
make install
```

Run the backend:

```bash
make dev-backend
```

Run the frontend in a second terminal:

```bash
make dev-frontend
```

Vite serves <http://localhost:5173> and proxies `/api` and `/health` to FastAPI on port 8080.

## Quality gates

```bash
make lint
make test
make build
```

Or run the project-prescribed commands directly:

```bash
cd backend
.venv/bin/ruff check .
.venv/bin/pytest

cd ../frontend
npm run lint
npm run test -- --run
npm run build
```

## Repository layout

```text
backend/       FastAPI application and backend tests
frontend/      React, TypeScript, Vite, and frontend tests
data/runs/     Persisted forecast-run manifests and validated frames
data/output/   Validated generated MP4 videos
data/state/    SQLite metadata and persistent application state
```

Configuration uses environment variables with the `IMGW_` prefix. See [`.env.example`](.env.example).

## Check one IMGW frame

The lightweight CLI performs one GET and validates the response MIME type, body size,
JPEG structure, and dimensions. It does not fetch a complete forecast run:

```bash
cd backend
.venv/bin/python -m app.cli check-imgw
```

Use an explicit timezone-aware source timestamp when diagnosing a known frame:

```bash
.venv/bin/python -m app.cli check-imgw \
  --timestamp 2026-08-29T11:00:00Z \
  --save ../data/runs/manual-check.jpg
```

Input timestamps are converted to UTC before constructing IMGW filenames. When no
timestamp is supplied, the command probes the current 10-minute UTC slot and can fall
back through `IMGW_MAX_START_FALLBACK_STEPS` earlier slots when IMGW returns HTTP 404.
It still retrieves only one valid frame.

## Time model

- Internal timestamps are timezone-aware UTC datetimes.
- UI/display timestamps use `Europe/Warsaw`, including daylight-saving transitions.
- The default sequence is eight hours inclusive at ten-minute intervals: 49 frames.
- Missing newest start frames may fall back by six intervals by default.
- Fallback applies only to HTTP 404. Transport, server, and validation failures remain
  visible errors.

Live IMGW imagery verified that MERGE filenames encode the frame's forecast valid time
in UTC. For example, `MERGE_MERGE_10_2026-08-29_11_00_00.jpg` visibly labels itself
`11:00 UTC`, while its embedded model start is `10:50Z`. The filename is therefore not
a stable publication/run identifier; collected frames must remain scoped to a local
forecast-run snapshot.

## Current HTTP endpoints

- `GET /health` — lightweight liveness response
- `GET /api/status` — server time, reachability data, refresh history/error, and scheduler status
- `GET /api/runs` — newest-first historical run summaries
- `GET /api/runs/latest` — complete latest run with ordered frame metadata
- `GET /api/runs/{run_id}` — one run with ordered frame metadata
- `GET /api/runs/{run_id}/frames/{frame_index}` — validated immutable JPEG
- `POST /api/runs/refresh` — start a non-blocking forecast refresh
- `GET /api/videos` — newest-first generated-video metadata
- `GET /api/videos/{video_id}` — one video generation and lifecycle state
- `POST /api/runs/{run_id}/videos` — start non-blocking MP4 generation
- `DELETE /api/videos/{video_id}` — remove a finished generation and its MP4
- `GET /api/videos/{video_id}/file` — stream a completed MP4

Run DTOs expose UTC timestamps, display-timezone metadata, status, progress, coverage,
missing timestamps, freshness, source traceability, and relative frame URLs. They never
expose local filesystem paths. Frame responses use immutable caching and SHA-256 ETags.

Explore the current data without React:

```bash
curl http://localhost:8080/api/runs
curl http://localhost:8080/api/runs/latest
curl -o frame.jpg http://localhost:8080/api/runs/RUN_ID/frames/0
```

Substitute `RUN_ID`, or use any `frame_url` returned by `/api/runs/latest`, for the final
command. Start a manual refresh with:

```bash
curl -X POST http://localhost:8080/api/runs/refresh
```

The refresh endpoint returns HTTP 202 immediately. Poll `/api/runs` for status and frame
progress. A concurrent refresh is rejected with HTTP 409.

## Automatic refresh

Automatic refresh uses APScheduler and remains disabled by default. Enable the
recommended small-delay schedule in `.env`:

```dotenv
IMGW_SCHEDULER_ENABLED=true
IMGW_SCHEDULER_CRON=2 * * * *
IMGW_SCHEDULER_MISFIRE_GRACE_SECONDS=60
```

Restart the container after changing these values. The job runs hourly at two minutes
past the hour in UTC, avoiding daylight-saving ambiguity while retaining a small IMGW
publication delay.
`/api/status` reports `running` and an aware `next_run_at`; the run panel displays that
time in `Europe/Warsaw`.

Each trigger first performs a conservative latest-sequence boundary probe. If the
resolved start and validated boundary-frame hashes match the newest completed snapshot,
the check is recorded as `skipped` and no duplicate run or full 49-frame download is
created. If the publication is new or its probed content changed, ingestion proceeds and
reuses the already validated probe frames. Manual and scheduled refreshes share the same
overlap lock, and skipped overlaps are logged. The last refresh result and IMGW error
are persisted in SQLite across restarts.

## Generate an MP4

Generate a source-sized H.264 animation from the latest completed forecast:

```bash
docker compose exec imgw-merge-weather \
  python -m app.cli generate-latest --mode source
```

Generate a 1080×1080 version from a specific run without stretching the weather map:

```bash
docker compose exec imgw-merge-weather \
  python -m app.cli generate --run RUN_ID --mode 1:1 --fps 5
```

Limit the animation to frames 6–24 and render traceable local/UTC timestamps onto
staging copies of the frames:

```bash
docker compose exec imgw-merge-weather \
  python -m app.cli generate --run RUN_ID --mode 1:1 --fps 7 \
  --start-frame 6 --end-frame 24 --timestamp-overlay
```

The equivalent REST request is:

```bash
curl -X POST http://localhost:8080/api/runs/RUN_ID/videos \
  -H 'Content-Type: application/json' \
  -d '{"mode":"source","fps":5,"start_frame_index":0,"end_frame_index":48,"timestamp_overlay":false}'
```

The request returns HTTP 202 immediately. Poll the returned `detail_url` until its state
is `completed` or `failed`. Completed responses include a `file_url`. Generation uses
chronological validated frames only, defaults to libx264 at 5 FPS, CRF 20, preset
`medium`, yuv420p, and fast-start MP4. The `1:1` mode applies proportional scale and
padding to 1080×1080. A requested frame range is inclusive. Optional timestamp overlays
show Warsaw local time and the traceable UTC source time without changing the persisted
IMGW frames. ffprobe must validate the codec, pixel format, duration, dimensions, and
file size before the artifact is published.

## Ingest a forecast run

Collect the newest complete eight-hour sequence:

```bash
cd backend
.venv/bin/python -m app.cli refresh
```

Or run it inside the production container:

```bash
docker compose exec imgw-merge-weather python -m app.cli refresh
```

An explicit start is also supported and never applies start fallback:

```bash
python -m app.cli refresh --start 2026-08-29T11:20:00Z
```

Runs are immutable snapshots under `data/runs/{run_id}/`. Each contains 49 validated
JPEGs when complete and an atomically updated `manifest.json` with source URLs, UTC
forecast times, dimensions, sizes, SHA-256 hashes, status, coverage, and errors.

Missing frames fail ingestion by default. Set `IMGW_ALLOW_MISSING_FRAMES=true` to permit
HTTP 404 gaps only when coverage remains at or above `IMGW_MIN_FRAME_COVERAGE` (default
0.90). Validation, transport, and persistence failures always fail the run. Existing
valid frames are preserved, and missing weather frames are never duplicated or
synthesized.

## SQLite persistence

Forecast run and frame metadata is stored in `data/state/app.db`. The database uses
SQLite WAL mode, foreign keys, and dedicated indexes for latest-run and historical-run
lookups. The application imports pre-database `manifest.json` files once, so runs
collected in Milestone 3 remain known after upgrading.

Schema changes use small forward-only migrations keyed by SQLite `PRAGMA user_version`.
The current schema version is 3. Video generations are stored separately from forecast
runs and include their selected frame bounds and overlay setting without rewriting the
forecast schema. If startup finds a forecast run left in `pending`, `probing`, or
`downloading`, or a video left in `pending` or `rendering`, it marks the interrupted
operation failed explicitly. Forecast recovery is also mirrored back to its manifest.
