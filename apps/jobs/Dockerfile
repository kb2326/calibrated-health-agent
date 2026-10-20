# Build from the repo root:  docker build -f apps/jobs/Dockerfile -t sync-job .
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Only the jobs package and its deps (health-core, health-data): no ADK.
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
# googleapiclient bundles ~600 static discovery docs (100+ MB); the job needs Forms only
# (the Health API client fetches its own discovery doc with static_discovery=False).
RUN uv sync --package jobs --no-dev --frozen --no-editable \
    && find .venv/lib/python3.13/site-packages/googleapiclient/discovery_cache/documents -type f ! -name forms.v1.json -delete \
    && find .venv -type d \( -name tests -o -name __pycache__ \) -prune -exec rm -rf {} +

FROM python:3.13-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CHA_DATA_DIR=/tmp/data
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY config/health.yaml ./config/health.yaml
RUN useradd --create-home --uid 10001 job
USER job
ENTRYPOINT ["python", "-m", "jobs.sync_job"]
