# ---- Frontend build stage ----
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build

# ---- Python build stage ----
FROM python:3.11-slim AS python-builder

WORKDIR /app

# 1) 先装 torch (最大依赖，单独一层缓存)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2) 再装项目依赖（只要 pyproject.toml 没变就命中缓存）
COPY pyproject.toml .
RUN pip install . psycopg2-binary

# ---- Runtime stage ----
FROM python:3.11-slim

# Install Chromium + Xvfb (virtual display) for non-headless browser automation
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    xvfb \
    x11-utils \
    fonts-noto-cjk \
    fonts-liberation \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_EXECUTABLE_PATH=/usr/bin/chromium
ENV DISPLAY=:99

WORKDIR /app
COPY --from=python-builder /usr/local /usr/local
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY data/cs_knowledge_structured.json data/

COPY --from=frontend-builder /app/frontend/out /app/frontend/out
COPY scripts/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8000
CMD ["/app/start.sh"]
