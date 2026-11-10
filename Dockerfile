FROM node:22-alpine AS ui
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY app/static ./app/static
RUN npm run vendor

FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && useradd --uid 10001 --create-home agent \
    && mkdir /data && chown agent:agent /data
COPY app ./app
COPY --from=ui /build/app/static ./app/static
COPY agent ./agent
USER agent
VOLUME ["/data"]
EXPOSE 9173
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9173/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9173", "--workers", "1", "--no-access-log"]
