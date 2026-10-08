# Static Angular compilation; only Python and assets remain at runtime.
FROM node:24-alpine AS frontend-build
WORKDIR /work/frontend
COPY frontend/package.json frontend/package-lock.json frontend/angular.json frontend/tsconfig.json frontend/tsconfig.app.json ./
COPY frontend/src ./src
RUN npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim-trixie AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FILAMENT_DB_PATH=/data/filaments.sqlite3
WORKDIR /srv/filament-manager
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 filament \
    && useradd --uid 10001 --gid filament --no-create-home filament \
    && mkdir -p /data \
    && chown filament:filament /data
COPY --chown=filament:filament app ./app
COPY --from=frontend-build --chown=filament:filament /work/frontend/dist/filament-manager/browser ./app/ui
USER 10001:10001
EXPOSE 8765

# Only the optional isolated worker includes the slicing executable.
FROM python-runtime AS slicer-runtime
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends prusa-slicer \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
EXPOSE 8767
CMD ["uvicorn", "app.slicer_worker:app", "--host", "0.0.0.0", "--port", "8767"]

# Default production build never ships the executable to the API container.
FROM python-runtime AS app-runtime
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
