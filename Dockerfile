FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-dev --extra server --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra server --no-editable


FROM python:3.14-slim

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin egress

COPY --from=build /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVER__HOST=0.0.0.0

WORKDIR /app
USER egress
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --start-interval=1s --retries=3 \
    CMD ["python", "-c", "import http.client, os, socket; connection = http.client.HTTPConnection(socket.gethostbyname(socket.gethostname()), int(os.environ.get('SERVER__PORT', '8000')), timeout=4); connection.request('GET', '/'); connection.getresponse()"]

ENTRYPOINT ["egress-proxy"]
