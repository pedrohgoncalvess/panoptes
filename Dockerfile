FROM python:3.12.13-slim-bookworm AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.16
COPY pyproject.toml uv.lock /app/
COPY packages /app/packages
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/src /app/backend/src
COPY workers/pyproject.toml /app/workers/pyproject.toml
COPY workers/src /app/workers/src
COPY migrations/pyproject.toml /app/migrations/pyproject.toml
COPY migrations/src /app/migrations/src
ARG SERVICE=backend
RUN uv sync --frozen --no-dev --no-editable --package panoptes-${SERVICE} \
    --python /usr/local/bin/python --no-managed-python

FROM python:3.12.13-slim-bookworm AS runtime
ARG SERVICE=backend
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
ENV HOME=/home/panoptes XDG_CONFIG_HOME=/home/panoptes/.config XDG_CACHE_HOME=/home/panoptes/.cache
WORKDIR /app
RUN groupadd --gid 10001 panoptes && useradd --create-home --uid 10001 --gid panoptes panoptes
COPY --from=builder /app/.venv /app/.venv
RUN if [ "$SERVICE" = "backend" ]; then python -m playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*; fi
RUN mkdir -p /app/.browser-sessions && chown 10001:10001 /app/.browser-sessions
COPY migrations/sql /app/migrations/sql
COPY agents /app/agents
COPY workers/parsers /app/workers/parsers
USER panoptes
