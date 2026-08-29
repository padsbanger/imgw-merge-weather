FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IMGW_HOST=0.0.0.0 \
    IMGW_PORT=8080 \
    IMGW_DATA_DIR=/data \
    IMGW_STATIC_DIR=/app/static

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data/runs /data/output /data/state \
    && chown -R app:app /data

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app
RUN python -m pip install --no-cache-dir ./backend

COPY --from=frontend-build /build/frontend/dist ./static

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
