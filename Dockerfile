# syntax=docker/dockerfile:1
FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    DATA_DIR=/data \
    TZ_NAME=America/Toronto

WORKDIR /app
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app app \
    && mkdir -p /data && chown app:app /data

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pipeline ./pipeline
COPY app ./app

USER app
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=4).status == 200 else 1)"

# One worker on purpose: background jobs and the scheduler live in this process.
CMD ["uvicorn", "--app-dir", "pipeline", "server:app", "--host", "0.0.0.0", "--port", "8787", "--workers", "1", "--proxy-headers", "--no-server-header"]


# Test stage: `docker build --target test .` runs the suite with no local Python needed.
FROM app AS test
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests ./tests
ENV DATA_DIR=/tmp/test-data ALLOW_NO_AUTH=1
RUN python -m pytest -q
