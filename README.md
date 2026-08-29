# imgw-merge-weather

Self-hosted weather viewer for collecting IMGW CMM MERGE precipitation forecast frames and, in later milestones, exploring forecast runs and generating MP4 animations.

**Milestones 0 and 1 are complete.** The repository provides a typed FastAPI backend, a React/Vite application shell, a validated asynchronous IMGW MERGE frame client, automated tests and linting, and a single-container Docker Compose deployment. Milestone 2 will add the canonical time model and forecast sequence.

## Quick start with Docker

```bash
cp .env.example .env
docker compose build
docker compose up -d
curl http://localhost:8080/health
```

Open <http://localhost:8080>. Runtime files are persisted under `./data`.

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
data/runs/     Forecast-run frame storage (future milestone)
data/output/   Generated videos (future milestone)
data/state/    Persistent application state (future milestone)
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

The timestamp's displayed clock fields are used exactly in the IMGW filename. The
actual filename timezone convention will be verified and documented in Milestone 2.

## Current HTTP endpoints

- `GET /health` — lightweight liveness response
- `GET /api/status` — typed service-foundation status

Forecast-run ingestion is not implemented yet. Milestone 1 retrieves only explicitly
requested individual frames and never invents missing weather data.
