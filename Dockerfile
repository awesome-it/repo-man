# Build stage: install deps with uv
# Version: set CI_COMMIT_TAG build-arg on tag pipelines (e.g. --build-arg CI_COMMIT_TAG=v0.1.0). If unset, use build timestamp.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
ARG CI_COMMIT_TAG
WORKDIR /app
COPY pyproject.toml README.md ./
# Version: CI_COMMIT_TAG (strip leading 'v') if set; otherwise 0.0.0+<build timestamp UTC>
RUN V="${CI_COMMIT_TAG#v}"; [ -z "$V" ] && V="0.0.0+$(date -u +%Y%m%d%H%M%S)" || true; \
    sed -i "s/^version = .*/version = \"$V\"/" pyproject.toml
COPY repo_man ./repo_man/
RUN uv sync --no-dev

# Run stage (version comes from builder stage; .venv has the package with CI_COMMIT_TAG version)
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
