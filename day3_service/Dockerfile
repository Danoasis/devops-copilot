# Multi-stage build (FUNDAMENTALS ch.6): build tooling never ships; runtime image
# carries only the venv + code and runs as a non-root user.
# Build from the REPO ROOT:  docker build -f day3_service/Dockerfile -t devops-copilot:local .

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
# Dependency layer first: cached unless pyproject/lock change (layer-cache order).
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project || uv sync --no-dev --no-install-project --frozen
# Source last: editing code reuses the cached dependency layer.
COPY common ./common
COPY day1_mcp ./day1_mcp
COPY day2_agent ./day2_agent
COPY day3_service ./day3_service
COPY day5_agentic_ops ./day5_agentic_ops
COPY evals ./evals
COPY README.md ./
RUN uv sync --no-dev

FROM python:3.12-slim
RUN useradd --create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
RUN mkdir -p /app/data && chown -R app:app /app/data
USER app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    COPILOT_DB=/app/data/copilot.db
EXPOSE 8000
CMD ["uvicorn", "day3_service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
