# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml .
# Install with CPU-only PyTorch (avoid 5GB CUDA wheels)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir . pgvector psycopg2-binary

# ---- runtime stage ----
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY scripts/ scripts/

# Chromium NOT needed on server — sync runs locally via nodriver daemon
# Server only serves API + agents

EXPOSE 8000

# Render/Railway inject PORT env var; use 1 worker to fit 512MB RAM
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
