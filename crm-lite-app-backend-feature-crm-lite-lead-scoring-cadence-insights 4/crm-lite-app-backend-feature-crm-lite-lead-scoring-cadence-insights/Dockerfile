# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev || uv pip install --system -e .

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

EXPOSE 8000
# uv sync (above) creates a project venv at /app/.venv rather than installing
# onto the image's global PATH — `uv run` is what resolves that venv, so a
# bare `uvicorn` here would fail with "executable file not found".
#
# --proxy-headers (+ --forwarded-allow-ips="*", safe here since Cloud Run's
# load balancer is the only thing that can reach this container directly)
# makes uvicorn trust Cloud Run's X-Forwarded-Proto header, so
# request.url.scheme reads "https" even though Cloud Run terminates TLS
# upstream and forwards plain HTTP internally. Required for
# utils.security.require_twilio_signature() to verify Twilio's inbound
# webhook signature correctly — that signature is computed over the https
# URL Twilio actually called, and would never match otherwise.
CMD ["uv", "run", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", \
    "--proxy-headers", "--forwarded-allow-ips=*"]
