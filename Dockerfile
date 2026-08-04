FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Deps layer first so source edits do not bust the cache.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" "pydantic-settings>=2.6" \
    "redis>=5.2" "structlog>=24.4" "httpx>=0.27" "typer>=0.15" "rich>=13.9"

COPY app ./app
COPY cli ./cli

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rdp \
    && chown -R rdp:rdp /srv
USER rdp

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
