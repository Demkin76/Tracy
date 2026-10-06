FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 tracy && useradd --uid 10001 --gid tracy --no-create-home tracy
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
COPY sdk/ sdk/
COPY scripts/ scripts/
COPY examples/ examples/
COPY deploy/daytona/runtime.py deploy/daytona/runtime.py
RUN pip install --no-cache-dir uv==0.12.23 && uv sync --locked --no-dev --no-editable
COPY frontend/dist/ frontend/dist/
RUN chmod -R a+rX /app && mkdir -p /app/data /app/backups && chmod 700 /app/data && ln -s /app/data/production.env /app/.env
EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/python", "-m", "deploy.daytona.runtime"]
