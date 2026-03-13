# Build stage: install deps with uv
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml README.md ./
COPY repo_man ./repo_man/
RUN uv sync --no-dev

# Run stage
FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app
ENV UV_SYSTEM_PYTHON=1
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY repo_man ./repo_man/
COPY pyproject.toml README.md ./

# Default: run serve on 8080; override with CMD
ENV REPO_MIRROR_REPO_ROOT=/data
EXPOSE 8080
VOLUME ["/data"]
ENTRYPOINT ["repo-man"]
CMD ["serve", "--bind", "0.0.0.0", "--port", "8080"]
