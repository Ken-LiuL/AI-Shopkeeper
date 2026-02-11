# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage ----
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY scripts/ scripts/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
