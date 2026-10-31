# The web app on Cloud Run (behind IAP). Build from the repo root:
#   docker build -f apps/webservice/Dockerfile -t web .
FROM node:22.18.0-slim AS ui
WORKDIR /ui
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/jobs ./apps/jobs
RUN uv sync --package health-web --no-dev --frozen --no-editable \
    && find .venv/lib/python3.13/site-packages/googleapiclient/discovery_cache/documents -type f -delete \
    && find .venv -type d \( -name tests -o -name __pycache__ \) -prune -exec rm -rf {} +

FROM python:3.13-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CHA_DATA_DIR=/tmp/data CHA_WEB_STATIC=/app/web
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY --from=ui /ui/out ./web
COPY config/health.yaml ./config/health.yaml
RUN useradd --create-home --uid 10001 web
USER web
ENTRYPOINT ["cha-web", "--cloud"]
