# syntax=docker/dockerfile:1.7

# ───────────────────────────────────────────────────────
# English-App — WhatsApp English Teaching Bot
# ───────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# System deps: fonts for Pillow image rendering + libs for async postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Python runtime tuning
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ───────────────────────────────────────────────────────
# Dependency layer — cached independently of app code
# ───────────────────────────────────────────────────────
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ───────────────────────────────────────────────────────
# Application code
# ───────────────────────────────────────────────────────
COPY . .

# Create directory for generated images (mounted as volume in compose)
RUN mkdir -p /app/audio_cache

# Healthcheck against FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

# Run the bot
CMD ["python", "main.py"]
