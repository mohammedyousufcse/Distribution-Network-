# Use official lightweight Python 3.11 slim image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first for efficient layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create an unprivileged user for security
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app

# Copy application source code, test suite, and example environment configuration
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser tests/ ./tests/
COPY --chown=appuser:appuser .env.example ./.env.example

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Healthcheck querying the existing /health endpoint without external curl dependency
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start FastAPI application via Uvicorn bound to 0.0.0.0 (respects cloud $PORT like Render/Railway)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
