# ---- Frontend build stage ----
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---- Python build stage ----
FROM python:3.11-slim AS python-builder

WORKDIR /app
COPY pyproject.toml .
# Install with CPU-only PyTorch (avoid 5GB CUDA wheels)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir . psycopg2-binary

# ---- Runtime stage ----
FROM python:3.11-slim

WORKDIR /app
COPY --from=python-builder /usr/local /usr/local
ARG CACHEBUST=2
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY data/cs_knowledge_structured.json data/

# Copy built frontend static export
COPY --from=frontend-builder /app/frontend/out /app/frontend/out

EXPOSE 8000

# Render/Railway inject PORT env var; use 1 worker to fit 512MB RAM
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
