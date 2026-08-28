FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM node:22-bookworm-slim AS ui

WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui ./
RUN npm run build

FROM python:3.13.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY --from=ui /ui/dist ./ui/dist
RUN uv sync --frozen --no-dev

ENTRYPOINT ["/app/.venv/bin/swing-bot"]