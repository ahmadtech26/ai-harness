FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
RUN uv sync --no-cache --group dev
CMD ["skill-ci", "--help"]
