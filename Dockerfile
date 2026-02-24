# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml .
# Install without neo4j to keep image light for Railway
RUN pip install --no-cache-dir --prefix=/install . \
    && pip install --no-cache-dir --prefix=/install pgvector psycopg2-binary

# ---- runtime stage ----
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY scripts/ scripts/

EXPOSE 8000

# Railway injects PORT env var
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
