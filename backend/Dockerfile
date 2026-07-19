# TraceX backend API image — ROADMAP Phase 12 (deployment wiring).
#
# Builds the three-layer FastAPI app (api.app:create_app) as an installed
# package so it imports regardless of working directory, and runs it as a
# non-root user (uid 1000) to match the k8s securityContext in
# deploy/k8s/api-deployment.yaml (runAsNonRoot + readOnlyRootFilesystem).
#
# Nothing is written to the image filesystem at runtime: PYTHONDONTWRITEBYTECODE
# stops .pyc writes, and every runtime write target (the SQLite DB, model
# artifacts, generated report PDFs) lives under /app/data, which the Deployment
# mounts as a writable volume. /tmp is an emptyDir. This keeps the container FS
# read-only in production.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install first with only the metadata present, so the dependency layer caches
# across source-only changes.
COPY pyproject.toml ./
COPY foundation ./foundation
COPY detection ./detection
COPY investigation ./investigation
COPY orchestration ./orchestration
COPY api ./api
COPY db ./db
COPY demo_data ./demo_data
COPY alembic ./alembic
COPY alembic.ini ./

# Runtime deps only (no [dev] — no ruff/mypy/pytest in the image).
RUN pip install --no-cache-dir .

# Non-root, and own the app + a data mount point for the writable volume.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER 1000

EXPOSE 8000

# Default config expects these to be provided by the platform (k8s secrets);
# ENV=prod makes Settings.validate_secrets() fail loudly at startup if the
# JWT / OpenRouter secrets are missing, rather than booting insecurely.
ENV ENV=prod \
    LOG_LEVEL=INFO

# create_app is a factory (per-Settings app instances), so --factory.
CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
