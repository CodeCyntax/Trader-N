# Production Dockerfile for Trader-N Autonomous Solana & Pump.fun Agent
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application source code
COPY . .

# Ensure data storage directory exists for persistent SQLite database
RUN mkdir -p /app/data_store

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE 8080

# Volume for database and learned memory persistence
VOLUME ["/app/data_store"]

# Entrypoint: start agent with web dashboard (respects $PORT if provided by cloud host)
CMD ["python", "main.py"]
