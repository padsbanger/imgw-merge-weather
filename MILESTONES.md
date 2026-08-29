# MILESTONES.md

## Project

**imgw-merge-weather**

This roadmap is ordered by dependency and product value.

The application should become useful as a live weather viewer before advanced automation or distribution features are added.

---

# Milestone 0 — Repository Foundation

**Status:** Complete (2026-08-29)

## Goal

Create a clean monorepo foundation for React/Vite and FastAPI.

## Deliverables

- [x] `backend/`
- [x] `frontend/`
- [x] `data/`
- [x] root `Dockerfile`
- [x] root `docker-compose.yml`
- [x] root `Makefile`
- [x] `.env.example`
- [x] `.gitignore`
- [x] `README.md`
- [x] `AGENTS.md`
- [x] `MILESTONES.md`
- [x] `DESIGN.md`

Backend:

- [x] Python 3.12 project
- [x] FastAPI
- [x] pydantic-settings
- [x] Ruff
- [x] pytest

Frontend:

- [x] React
- [x] TypeScript strict mode
- [x] Vite
- [x] TanStack Query
- [x] React Router
- [x] ESLint
- [x] Vitest
- [x] React Testing Library

## Acceptance Criteria

```bash
cd backend
ruff check .
pytest
```

passes.

```bash
cd frontend
npm run lint
npm run test -- --run
npm run build
```

passes.

---

# Milestone 1 — IMGW MERGE Client

**Status:** Complete (2026-08-29)

## Goal

Reliably construct and retrieve individual MERGE forecast frames.

## Deliverables

- [x] `ImgwMergeClient`
- [x] configurable IMGW base URL
- [x] exact filename generator
- [x] GET requests with browser-compatible headers
- [x] timeout handling
- [x] retry logic
- [x] exponential backoff
- [x] conservative concurrency
- [x] image-body validation
- [x] atomic writes
- [x] lightweight `check-imgw` CLI command

Known URL pattern:

```text
https://cmm.imgw.pl/wp-content/uploads/production/MERGE/MERGE_MERGE_10_YYYY-MM-DD_HH_MM_SS.jpg
```

## Tests

- [x] timestamp formatting
- [x] exact URL generation
- [x] valid JPEG
- [x] corrupt JPEG
- [x] HTML response with HTTP 200
- [x] empty response
- [x] timeout/retry behavior

## Acceptance Criteria

A single known frame can be downloaded and verified without involving FFmpeg.

Verified live on 2026-08-29 with one GET for
`MERGE_MERGE_10_2026-08-29_11_00_00.jpg`: HTTP 200, JPEG, 455588 bytes,
1700×1600 pixels. This confirms individual-frame retrieval only; filename timezone
semantics remain a Milestone 2 validation item.

---

# Milestone 2 — Time Model and Forecast Sequence

**Status:** Complete (2026-08-29)

## Goal

Create correct forecast timestamp logic.

## Deliverables

- [x] timezone-aware datetime handling
- [x] UTC canonical storage
- [x] Europe/Warsaw display conversion
- [x] `floor_to_interval()`
- [x] `build_frame_times()`
- [x] latest-cycle probing
- [x] configurable fallback
- [x] 8-hour / 10-minute forecast sequence

Default:

```text
interval = 10 minutes
horizon = 8 hours
frames = 49
```

## Critical Validation

Confirm through live IMGW requests whether MERGE filenames use:

- UTC,
- local Europe/Warsaw time,
- another convention.

Document the verified behavior.

Verified live on 2026-08-29. The file
`MERGE_MERGE_10_2026-08-29_11_00_00.jpg` visibly labels its valid time as
`29 August 2026 11:00 UTC`; Warsaw local time was 13:16 CEST. Its embedded model
start was `10:50Z`, which also confirms that the filename is the frame's UTC valid
time rather than the publication/model-start identifier. A second file named for
11:10 visibly labeled the frame 11:10 UTC.

## Acceptance Criteria

Given a cycle start, the backend generates the exact expected ordered frame sequence.

---

# Milestone 3 — Forecast Run Ingestion

**Status:** Complete (2026-08-29)

## Goal

Move from individual image downloads to complete forecast-run ingestion.

## Deliverables

Create explicit domain models:

- [x] ForecastRun
- [x] ForecastFrame

Run states:

```text
pending
probing
downloading
completed
failed
```

Store:

- [x] run ID
- [x] discovered timestamp
- [x] resolved forecast start
- [x] forecast end
- [x] expected frames
- [x] downloaded frames
- [x] missing timestamps
- [x] status
- [x] error information
- [x] manifest

Filesystem:

```text
data/runs/{run_id}/frames/
data/runs/{run_id}/manifest.json
```

## Missing Frame Behavior

Strict by default:

```text
ALLOW_MISSING_FRAMES=false
```

Optional:

```text
ALLOW_MISSING_FRAMES=true
MIN_FRAME_COVERAGE=0.90
```

Never synthesize or duplicate missing weather frames.

## Acceptance Criteria

The application can ingest one complete forecast run and persist it independently from video generation.

Verified live on 2026-08-29. Boundary probing found that the requested 11:40 UTC
sequence did not yet have its 19:40 endpoint, so start discovery fell back two intervals
to the newest complete 11:20–19:20 UTC sequence. All 49 JPEGs validated and were stored
with 100% coverage under run `merge_20260829t114240z_6d519288`.

---

# Milestone 4 — Database and Persistence

**Status:** Complete (2026-08-29)

## Goal

Persist forecast metadata across restarts.

## Deliverables

- [x] SQLite database
- [x] forecast run table
- [x] forecast frame table
- [x] indexes for latest-run lookup
- [x] startup recovery
- [x] migrations or a documented lightweight schema strategy

Application restart must preserve:

- [x] known forecast runs
- [x] frame metadata
- [x] generated-video metadata can be added through forward-only migrations later
- [x] application state

## Acceptance Criteria

Restarting the backend does not lose the list of collected runs.

SQLite schema version 1 uses `PRAGMA user_version` for lightweight forward-only
migrations. On first startup it imports existing filesystem manifests, and subsequent
starts treat the database as metadata source of truth. Interrupted `pending`, `probing`,
or `downloading` runs are explicitly failed and mirrored back to their manifest instead
of remaining stuck. The Milestone 3 live run and all 49 frame records remained available
after a production container rebuild and restart.

---

# Milestone 5 — Forecast REST API

**Status:** Complete (2026-08-29)

## Goal

Expose forecast data independently from the frontend.

## Deliverables

```text
GET /health
GET /api/status

GET /api/runs
GET /api/runs/latest
GET /api/runs/{run_id}
GET /api/runs/{run_id}/frames/{frame_index}

POST /api/runs/refresh
```

API should expose:

- [x] latest run
- [x] historical runs
- [x] frame timestamps
- [x] frame URLs
- [x] freshness metadata
- [x] run status
- [x] download progress

## Acceptance Criteria

The complete latest forecast can be explored through REST without React.

The API returns typed run summaries and details without exposing local filesystem paths.
Validated JPEGs are served from path-contained run storage with immutable caching and
SHA-256 ETags. Manual refresh returns HTTP 202, runs outside the request lifecycle, and
returns HTTP 409 when another refresh is active. Freshness is calculated centrally from
the resolved forecast start using `FRESH`, `DELAYED`, and `STALE` thresholds.

---

# Milestone 6 — Weather Viewer MVP

**Status:** Complete (2026-08-29)

## Goal

Build the first genuinely useful browser experience.

The application should now be useful even before MP4 generation is implemented.

## Deliverables

React routes:

```text
/
 /runs/:runId
```

Main screen:

- [x] large MERGE image viewer
- [x] selected timestamp
- [x] timeline
- [x] frame scrubber
- [x] previous/next frame
- [x] play
- [x] pause
- [x] latest run indicator
- [x] weather-data freshness
- [x] run metadata

Timeline should visually emphasize time.

Example:

```text
10:50 ━━ 11:50 ━━ 12:50 ━━ 13:50 ━━ ... ━━ 18:50
                   ●
                 12:50
```

## Interaction

- [x] click timestamp → change frame
- [x] drag/scrub timeline → change frame
- [x] play animation
- [x] stop at end or loop depending on chosen behavior
- [x] keyboard arrow navigation where practical

## Acceptance Criteria

A user can open the app and understand the latest precipitation forecast without generating a video.

The viewer loops valid frames at 2 FPS and keeps unavailable timestamps visibly
unavailable instead of substituting weather data. The native range control supports
pointer scrubbing and keyboard arrows; the focused image viewer also supports left/right
navigation. Local `Europe/Warsaw` time, UTC source time, forecast offset, freshness,
latest-run state, run metadata, and recent historical runs remain visible around the
undistorted forecast image.

---

# Milestone 7 — Freshness and Live Data UX

**Status:** Complete (2026-08-29)

## Goal

Make it obvious whether the displayed weather data is current.

## Deliverables

Central freshness logic:

```text
LIVE
FRESH
DELAYED
STALE
OFFLINE
```

Suggested initial thresholds:

```text
FRESH      < 15 minutes
DELAYED    15–30 minutes
STALE      > 30 minutes
```

UI:

```text
● LIVE · updated 3m ago
```

Show:

- [x] current local time
- [x] source update time
- [x] data age
- [x] scheduler state
- [x] backend reachability

## Acceptance Criteria

The user never has to guess whether they are looking at old forecast data.

The latest temporally fresh run is labeled `LIVE`; a fresh historical run remains
`FRESH`. The backend supplies centralized `FRESH`, `DELAYED`, and `STALE` classification,
while the UI adds `OFFLINE` when status polling fails and continues to label any cached
imagery honestly. The header clock updates in `Europe/Warsaw`. Source time is shown in
both Warsaw and UTC, and the compact live-data panel exposes age, reachability, refresh
activity/result, last IMGW error, scheduler state, and the next automatic run when
scheduling is enabled.

---

# Milestone 8 — Forecast Run Browser

**Status:** Complete (2026-08-29)

## Goal

Allow navigation between forecast publications.

## Deliverables

Compact run list:

```text
● 11:20 latest
  11:10
  11:00
  10:50
```

Features:

- [x] load historical run
- [x] preserve selected forecast offset if possible
- [x] clearly mark latest
- [x] show missing/incomplete runs
- [x] show ingestion failures

## Acceptance Criteria

The user can inspect how the forecast looked in recent publication cycles.

The compact run browser lists recent publications newest-first, distinguishes the latest
completed forecast from historical snapshots, and keeps failed or partial ingestion
attempts visible. Run changes carry the selected minute offset in the route and choose
the nearest valid frame when that exact offset is unavailable. Selecting an incomplete
or failed run exposes its progress, exact ingestion error, and source UTC timestamps for
missing frames without inventing replacement weather data.

---

# Milestone 9 — FFmpeg Video Generation

**Status:** Complete (2026-08-29)

## Goal

Generate validated MP4 weather animations from an existing forecast run.

## Deliverables

Create separate `VideoGeneration` domain model.

States:

```text
pending
rendering
completed
failed
```

Default encoding:

```text
H.264
yuv420p
5 FPS
CRF 20
preset medium
```

Initial modes:

```text
source
1:1
```

Square:

```text
1080x1080
```

Use scale + padding.

Never stretch imagery.

Validate with `ffprobe`.

## Output

Example:

```text
merge_2026-08-29_12-50_to_20-50_<id>.mp4
```

## Acceptance Criteria

A completed forecast run can reliably produce a browser-compatible MP4.

Video generation is a separate persisted domain with `pending`, `rendering`,
`completed`, and `failed` states and a one-to-many relationship with forecast runs.
The source and 1080×1080 modes use chronological validated frames without stretching
or filling weather-data gaps. FFmpeg runs without a shell using whitelisted encoding
settings; output remains temporary until ffprobe verifies an H.264/yuv420p video stream,
positive duration, expected dimensions, and a sensible size. Interrupted operations are
explicitly failed on startup, duplicate active renders are rejected, and completed MP4s
are available through typed REST and CLI contracts.

---

# Milestone 10 — Video UI

**Status:** Complete (2026-08-29)

## Goal

Integrate video generation without turning the application into a video-job dashboard.

## Deliverables

Secondary action:

```text
Generate video
```

Configuration drawer/modal:

- [x] run
- [x] range
- [x] FPS
- [x] output format
- [x] optional timestamp overlay

Video outputs:

- [x] progress
- [x] native HTML5 player
- [x] download
- [x] delete
- [x] metadata

## Acceptance Criteria

Video generation is available, but the main weather viewer remains the dominant UI.

The current run panel exposes one compact `Generate video` action. It opens a responsive
drawer over the existing weather workspace with an explicit frame range, validated FPS,
source or padded 1080×1080 output previews, and an optional Warsaw/UTC timestamp overlay.
Active generations poll in the drawer; completed artifacts use native browser playback
and expose range, FPS, size, dimensions, duration, overlay state, download, and
confirmation-protected deletion. Timestamp overlays are rendered onto staging copies,
so the persisted IMGW source frames remain unmodified.

---

# Milestone 11 — Automatic Refresh

**Status:** Complete (2026-08-29)

## Goal

Keep the latest forecast current automatically.

## Deliverables

Use APScheduler.

Default disabled:

```text
SCHEDULER_ENABLED=false
```

Configured production schedule:

```text
2 * * * *
```

Flow:

```text
probe latest
→ detect whether publication is new
→ ingest
→ update latest pointer
```

Requirements:

- [x] prevent overlapping refreshes
- [x] prevent duplicate runs
- [x] log skipped refreshes
- [x] expose next scheduled run
- [x] expose last IMGW error

## Acceptance Criteria

A homelab instance can remain current without manual intervention.

An asyncio-native APScheduler job is created with one in-memory cron trigger, UTC-aware
fire times, coalescing, and a single allowed instance. The existing refresh coordinator
remains the shared overlap guard for scheduled and manual work. Before ingestion, a
conservative boundary probe compares validated remote frame hashes with the latest
completed snapshot; unchanged forecasts are logged and persisted as a `skipped` refresh
without creating a run or downloading all 49 frames. New runs reuse the validated probe
frames. `/api/status` exposes scheduler state, the next run, the last refresh result,
and the persisted last IMGW error. Scheduling remains disabled by default.

---

# Milestone 12 — Docker Production Deployment

## Goal

Provide one-command homelab deployment.

## Architecture

```text
Node build stage
→ Vite dist

Python runtime
→ FastAPI
→ FFmpeg
→ React static assets
```

Final runtime should not require Node.

## Deliverables

- [ ] multi-stage Dockerfile
- [ ] Docker Compose
- [ ] persistent `./data:/data`
- [ ] non-root runtime user
- [ ] healthcheck
- [ ] `restart: unless-stopped`
- [ ] SPA fallback

Default URL:

```text
http://HOMELAB_IP:8080
```

## Acceptance Criteria

```bash
docker compose build
docker compose up -d
curl http://localhost:8080/health
```

passes.

---

# Milestone 13 — Retention and Storage Management

## Goal

Keep disk use predictable.

## Deliverables

Initial settings:

```text
FRAME_RETENTION_HOURS=24
OUTPUT_RETENTION_DAYS=7
```

Add policy options:

- [ ] keep latest N runs
- [ ] keep one hourly run longer
- [ ] remove old frames
- [ ] keep manifests/metadata
- [ ] prune old generated videos
- [ ] display disk usage in status

Never delete outside `/data`.

## Acceptance Criteria

The application can run unattended without uncontrolled storage growth.

---

# Milestone 14 — Multiple Video Presets

## Goal

Support common publication targets.

## Deliverables

```text
1:1
16:9
9:16
source
```

Suggested use:

```text
1:1   Telegram/social
16:9  desktop/YouTube
9:16  Shorts/Stories
```

Frontend should preview the target framing.

## Acceptance Criteria

One forecast run can generate multiple independently stored output formats.

---

# Milestone 15 — RainGRS + MERGE Unified Timeline

## Goal

Combine current/observed precipitation with the forecast.

## Product Concept

```text
RainGRS observed           MERGE forecast
←─────────────────────│────────────────────────→
                      NOW
```

## Deliverables

- [ ] investigate RainGRS frame URL scheme
- [ ] ingest observed frames
- [ ] merge data sources on one timeline
- [ ] visually distinguish observation vs forecast
- [ ] handle transition around NOW
- [ ] document timestamp conventions

## Acceptance Criteria

The viewer shows recent actual precipitation and smoothly continues into the forecast horizon.

---

# Milestone 16 — Run-to-Run Comparison

## Goal

See how the MERGE forecast changes between update cycles.

Example:

```text
11:20 run
vs
10:20 run
```

## Potential Deliverables

- [ ] side-by-side frames
- [ ] synchronized timestamp selection
- [ ] opacity slider
- [ ] difference mode later

## Acceptance Criteria

A user can compare the same forecast timestamp from two different MERGE publications.

---

# Milestone 17 — Notifications and Distribution

## Goal

Push completed forecasts beyond the web UI.

Potential integrations:

- [ ] Telegram notification
- [ ] Telegram MP4 delivery
- [ ] Discord notification
- [ ] webhook
- [ ] Home Assistant event

Keep integrations outside the core weather-ingestion domain.

## Acceptance Criteria

At least one optional notification provider can report a newly available forecast/video.

---

# Milestone 18 — Operational Hardening

## Goal

Make the project reliable for long-running homelab use.

## Deliverables

- [ ] structured logging
- [ ] graceful shutdown
- [ ] interrupted-operation recovery
- [ ] disk-space warnings
- [ ] HTTP failure metrics
- [ ] scheduler health
- [ ] configurable limits
- [ ] Basic Auth option
- [ ] reverse proxy documentation
- [ ] backup/restore documentation

## Acceptance Criteria

The application can recover from common network, container, and IMGW availability failures without manual database repair.

---

# Definition of Done

A milestone is complete only when:

1. implementation is finished,
2. backend tests pass,
3. frontend tests pass when applicable,
4. lint passes,
5. production build passes,
6. documentation is updated,
7. no known critical bug is deferred as a TODO,
8. the user-visible workflow is manually verified.
