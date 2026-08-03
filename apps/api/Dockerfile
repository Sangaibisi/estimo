# Build context is the repository root: docker build -f apps/api/Dockerfile .
# ADR-0006: containers are the only supported runtime.

FROM python:3.14.6-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependency layer: manifests only, so third-party deps cache across code changes.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/core/pyproject.toml packages/core/
COPY packages/gateway/pyproject.toml packages/gateway/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package estimo-api


FROM python:3.14.6-slim-trixie
LABEL org.opencontainers.image.source="https://github.com/Sangaibisi/estimo" \
      org.opencontainers.image.licenses="Apache-2.0"
RUN groupadd --system --gid 999 app \
    && useradd --system --uid 999 --gid app --home /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/apps/api/alembic.ini /app/apps/api/alembic.ini
COPY --from=builder --chown=app:app /app/apps/api/alembic /app/apps/api/alembic
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
# Slim images ship no curl/wget; probe with the stdlib instead.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
USER app
CMD ["uvicorn", "estimo_api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
