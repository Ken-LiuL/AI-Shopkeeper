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

# 安装 Chromium（nodriver 会自动找到系统 Chrome，用于 h5guard mtgsig 签名）
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    && rm -rf /var/lib/apt/lists/*

ENV HEADLESS=true

EXPOSE 8000

# Render/Railway inject PORT env var; use 1 worker to fit 512MB RAM
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
