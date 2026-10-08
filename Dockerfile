# Compile Angular separately; runtime contains Python and static assets only.
FROM node:24-alpine AS frontend-build
WORKDIR /work/frontend
COPY frontend/package.json frontend/angular.json frontend/tsconfig.json frontend/tsconfig.app.json ./
COPY frontend/src ./src
RUN npm install --no-audit --no-fund && npm run build

FROM python:3.12-slim
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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
