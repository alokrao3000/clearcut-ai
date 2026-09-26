# The native stack WeasyPrint needs is installed here rather than probed and missed: on a
# server there is no one to read the "install GTK" hint, so the image simply has Pango.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libjpeg62-turbo \
        libopenjp2-7 \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Not root. The API writes nothing to disk that matters, so it does not need to.
RUN useradd --create-home --uid 10001 clearcut && chown -R clearcut:clearcut /app
USER clearcut

EXPOSE 8000

# Liveness only. Readiness is /api/health/ready and names the failing component; an
# orchestrator that restarts on a missing Redis would be restarting for no reason.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# Migrations are a deploy step, not a startup step: several replicas booting together would
# race each other through the same DDL. See the `migrate` service in docker-compose.prod.yml.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
