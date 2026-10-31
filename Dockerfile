FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLOWSYNC_EXPERIMENT_DB=/app/data/experiments.sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends sumo sumo-tools curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY flowsync ./flowsync
RUN pip install --no-cache-dir '.[api,sumo]'
RUN mkdir -p /app/data
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=3 CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" >/dev/null || exit 1
CMD ["sh", "-c", "uvicorn flowsync.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
