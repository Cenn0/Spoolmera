# Static Angular compilation; only Python and assets remain at runtime.
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS frontend-build
WORKDIR /work/frontend
COPY frontend/package.json frontend/package-lock.json frontend/angular.json frontend/tsconfig.json frontend/tsconfig.app.json ./
COPY frontend/src ./src
COPY frontend/public ./public
COPY frontend/scripts/collect-license-notices.mjs ./scripts/
RUN npm ci --no-audit --no-fund \
    && node scripts/collect-license-notices.mjs \
    && npm run build

FROM python:3.12-slim-trixie@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS python-runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPOOLMERA_DB_PATH=/data/spoolmera.sqlite3
WORKDIR /srv/spoolmera
COPY requirements.txt ./
COPY LICENSE THIRD_PARTY_LICENSES.md /usr/share/doc/spoolmera/
COPY scripts/collect_python_licenses.py ./scripts/
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && python scripts/collect_python_licenses.py \
        --requirements requirements.txt \
        --output /usr/share/doc/spoolmera/python-licenses.txt \
        --manifest /usr/share/doc/spoolmera/python-dependencies.json \
    && groupadd --gid 10001 spoolmera \
    && useradd --uid 10001 --gid spoolmera --no-create-home spoolmera \
    && mkdir -p /data \
    && chown spoolmera:spoolmera /data
COPY --chown=spoolmera:spoolmera app ./app
COPY --chown=spoolmera:spoolmera scripts/backup.py scripts/restore.py ./scripts/
COPY --from=frontend-build --chown=spoolmera:spoolmera /work/frontend/dist/spoolmera/browser ./app/ui
COPY --from=frontend-build /work/frontend/third-party-licenses.txt /usr/share/doc/spoolmera/npm-licenses.txt
USER 10001:10001
EXPOSE 8765

# Only the optional isolated worker includes the slicing executable.
FROM python-runtime AS slicer-runtime
USER root
ARG PRUSA_SLICER_VERSION=2.9.2+dfsg-1
RUN apt-get update \
    && apt-get install -y --no-install-recommends prusa-slicer=${PRUSA_SLICER_VERSION} \
    && test -s /usr/share/doc/prusa-slicer/copyright \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
EXPOSE 8767
CMD ["uvicorn", "app.slicer_worker:app", "--host", "0.0.0.0", "--port", "8767"]

# Default production build never ships the executable to the API container.
FROM python-runtime AS app-runtime
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--limit-concurrency", "64"]
