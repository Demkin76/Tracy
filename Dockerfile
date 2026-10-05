FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 tracy && useradd --uid 10001 --gid tracy --no-create-home tracy
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
COPY sdk/ sdk/
COPY scripts/ scripts/
COPY examples/ examples/
RUN pip install --no-cache-dir uv==0.12.23 && uv sync --locked --no-dev --no-editable
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /app/data && chown -R tracy:tracy /app/data
USER tracy
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD ["/app/.venv/bin/python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=4)"]
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
