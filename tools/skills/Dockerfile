FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS base

COPY --from=ghcr.io/astral-sh/uv:0.9@sha256:538e0b39736e7feae937a65983e49d2ab75e1559d35041f9878b7b7e51de91e4 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"

WORKDIR /app

FROM base AS source
COPY pyproject.toml uv.lock ./
COPY src ./src

FROM source AS test
COPY tests ./tests
RUN uv sync --no-cache --locked --group dev
CMD ["pytest", "-q"]

# Last, so a plain `docker build` (deploy/release/build.sh) gets the runtime: no dev group, no tests.
FROM source AS runtime
RUN uv sync --no-cache --locked --no-dev
CMD ["skill-ci", "--help"]
