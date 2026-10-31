# One Dockerfile, three targets. Each service image gets only what it needs, and none of them
# contains database settings at build time (they come from the environment at run time).
#   app        -> api, app-worker, scheduler
#   exec       -> exec-worker (drives sandbox-docker through the Docker SDK, a normal dependency)
#   inference  -> inference-worker (adds PyTorch / ONNX Runtime in TCK-1103)

FROM ghcr.io/astral-sh/uv:0.13 AS uv

FROM python:3.12-slim AS base
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
WORKDIR /srv
# Every process finds app, domain_core, workers and cli however it was started: the celery command
# only puts its folder on the path while loading, so a package first imported later inside a task
# (domain_core for the sweeper) was otherwise not found.
ENV PYTHONPATH=/srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN useradd --uid 10000 --no-create-home appuser
USER appuser

FROM base AS app

FROM base AS exec

FROM base AS inference
