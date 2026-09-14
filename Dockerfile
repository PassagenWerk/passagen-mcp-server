# Build from this repository root:
#   docker build --build-context passagen-core=../passagen-core -t passagen-mcp-server:local .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /src
COPY --from=passagen-core pyproject.toml uv.lock README.md LICENSE ./passagen-core/
COPY --from=passagen-core src ./passagen-core/src
COPY pyproject.toml uv.lock README.md LICENSE ./passagen-mcp-server/
COPY src ./passagen-mcp-server/src

WORKDIR /src/passagen-mcp-server
ENV UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
RUN mkdir -p /app && uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --system --gid "${APP_GID}" passagen \
    && useradd --system --uid "${APP_UID}" --gid "${APP_GID}" \
      --create-home --shell /usr/sbin/nologin passagen
WORKDIR /app
COPY --from=build --chown=passagen:passagen /app/.venv /app/.venv
RUN mkdir -p /data && chown passagen:passagen /data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER passagen
EXPOSE 8766
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=3)"
CMD ["passagen-mcp", "serve", "--data-dir", "/data", "--host", "0.0.0.0", "--allow-host", "passagen-mcp"]
