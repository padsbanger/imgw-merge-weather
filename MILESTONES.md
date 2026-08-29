# MILESTONES.md

## Project

**imgw-merge-weather**

This roadmap is ordered by dependency and product value.

The application should become useful as a live weather viewer before advanced automation or distribution features are added.

---

# Milestone 0 — Repository Foundation

## Goal

Create a clean monorepo foundation for React/Vite and FastAPI.

## Deliverables

- [ ] `backend/`
- [ ] `frontend/`
- [ ] `data/`
- [ ] root `Dockerfile`
- [ ] root `docker-compose.yml`
- [ ] root `Makefile`
- [ ] `.env.example`
- [ ] `.gitignore`
- [ ] `README.md`
- [ ] `AGENTS.md`
- [ ] `MILESTONES.md`
- [ ] `DESIGN.md`

Backend:

- [ ] Python 3.12 project
- [ ] FastAPI
- [ ] pydantic-settings
- [ ] Ruff
- [ ] pytest

Frontend:

- [ ] React
- [ ] TypeScript strict mode
- [ ] Vite
- [ ] TanStack Query
- [ ] React Router
- [ ] ESLint
- [ ] Vitest
- [ ] React Testing Library

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

## Goal

Reliably construct and retrieve individual MERGE forecast frames.

## Deliverables

- [ ] `ImgwMergeClient`
- [ ] configurable IMGW base URL
- [ ] exact filename generator
- [ ] GET requests with browser-compatible headers
- [ ] timeout handling
- [ ] retry logic
- [ ] exponential backoff
- [ ] conservative concurrency
- [ ] image-body validation
- [ ] atomic writes
- [ ] lightweight `check-imgw` CLI command

Known URL pattern:

```text
https://cmm.imgw.pl/wp-content/uploads/production/MERGE/MERGE_MERGE_10_YYYY-MM-DD_HH_MM_SS.jpg
```

## Tests

- [ ] timestamp formatting
- [ ] exact URL generation
- [ ] valid JPEG
- [ ] corrupt JPEG
- [ ] HTML response with HTTP 200
- [ ] empty response
- [ ] timeout/retry behavior

## Acceptance Criteria

A single known frame can be downloaded and verified without involving FFmpeg.

---

# Milestone 2 — Time Model and Forecast Sequence

## Goal

Create correct forecast timestamp logic.

## Deliverables

- [ ] timezone-aware datetime handling
- [ ] UTC canonical storage
- [ ] Europe/Warsaw display conversion
- [ ] `floor_to_interval()`
- [ ] `build_frame_times()`
- [ ] latest-cycle probing
- [ ] configurable fallback
- [ ] 8-hour / 10-minute forecast sequence

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

## Acceptance Criteria

Given a cycle start, the backend generates the exact expected ordered frame sequence.

---

# Milestone 3 — Forecast Run Ingestion

## Goal

Move from individual image downloads to complete forecast-run ingestion.

## Deliverables

Create explicit domain models:

- [ ] ForecastRun
- [ ] ForecastFrame

Run states:

```text
pending
probing
downloading
completed
failed
```

Store:

- [ ] run ID
- [ ] discovered timestamp
- [ ] resolved forecast start
- [ ] forecast end
- [ ] expected frames
- [ ] downloaded frames
- [ ] missing timestamps
- [ ] status
- [ ] error information
- [ ] manifest

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

---

# Milestone 4 — Database and Persistence

## Goal

Persist forecast metadata across restarts.

## Deliverables

- [ ] SQLite database
- [ ] forecast run table
- [ ] forecast frame table
- [ ] indexes for latest-run lookup
- [ ] startup recovery
- [ ] migrations or a documented lightweight schema strategy

Application restart must preserve:

- [ ] known forecast runs
- [ ] frame metadata
- [ ] generated-video metadata later
- [ ] application state

## Acceptance Criteria

Restarting the backend does not lose the list of collected runs.

---

# Milestone 5 — Forecast REST API

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

- [ ] latest run
- [ ] historical runs
- [ ] frame timestamps
- [ ] frame URLs
- [ ] freshness metadata
- [ ] run status
- [ ] download progress

## Acceptance Criteria

The complete latest forecast can be explored through REST without React.

---

# Milestone 6 — Weather Viewer MVP

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

- [ ] large MERGE image viewer
- [ ] selected timestamp
- [ ] timeline
- [ ] frame scrubber
- [ ] previous/next frame
- [ ] play
- [ ] pause
- [ ] latest run indicator
- [ ] weather-data freshness
- [ ] run metadata

Timeline should visually emphasize time.

Example:

```text
10:50 ━━ 11:50 ━━ 12:50 ━━ 13:50 ━━ ... ━━ 18:50
                   ●
                 12:50
```

## Interaction

- [ ] click timestamp → change frame
- [ ] drag/scrub timeline → change frame
- [ ] play animation
- [ ] stop at end or loop depending on chosen behavior
- [ ] keyboard arrow navigation where practical

## Acceptance Criteria

A user can open the app and understand the latest precipitation forecast without generating a video.

---

# Milestone 7 — Freshness and Live Data UX

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

- [ ] current local time
- [ ] source update time
- [ ] data age
- [ ] scheduler state
- [ ] backend reachability

## Acceptance Criteria

The user never has to guess whether they are looking at old forecast data.

---

# Milestone 8 — Forecast Run Browser

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

- [ ] load historical run
- [ ] preserve selected forecast offset if possible
- [ ] clearly mark latest
- [ ] show missing/incomplete runs
- [ ] show ingestion failures

## Acceptance Criteria

The user can inspect how the forecast looked in recent publication cycles.

---

# Milestone 9 — FFmpeg Video Generation

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

---

# Milestone 10 — Video UI

## Goal

Integrate video generation without turning the application into a video-job dashboard.

## Deliverables

Secondary action:

```text
Generate video
```

Configuration drawer/modal:

- [ ] run
- [ ] range
- [ ] FPS
- [ ] output format
- [ ] optional timestamp overlay

Video outputs:

- [ ] progress
- [ ] native HTML5 player
- [ ] download
- [ ] delete
- [ ] metadata

## Acceptance Criteria

Video generation is available, but the main weather viewer remains the dominant UI.

---

# Milestone 11 — Automatic Refresh

## Goal

Keep the latest forecast current automatically.

## Deliverables

Use APScheduler.

Default disabled:

```text
SCHEDULER_ENABLED=false
```

Recommended production schedule:

```text
2,12,22,32,42,52 * * * *
```

Flow:

```text
probe latest
→ detect whether publication is new
→ ingest
→ update latest pointer
```

Requirements:

- [ ] prevent overlapping refreshes
- [ ] prevent duplicate runs
- [ ] log skipped refreshes
- [ ] expose next scheduled run
- [ ] expose last IMGW error

## Acceptance Criteria

A homelab instance can remain current without manual intervention.

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
