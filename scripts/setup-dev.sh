#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "🚀 AI Store Manager - Dev Environment Setup"
echo "============================================"

# 1. Start infrastructure
echo ""
echo "📦 Starting Docker services..."
docker compose up -d postgres neo4j redis

# 2. Wait for health
echo ""
echo "⏳ Waiting for services to be healthy..."

wait_for_service() {
    local service=$1
    local max_attempts=30
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if docker compose ps "$service" 2>/dev/null | grep -q "healthy"; then
            echo "  ✅ $service is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    echo "  ❌ $service failed to become healthy after ${max_attempts} attempts"
    return 1
}

wait_for_service postgres
wait_for_service neo4j
wait_for_service redis

# 3. Run Neo4j migrations (not auto-loaded like PG)
echo ""
echo "🔄 Running Neo4j migrations..."
if [ -f migrations/neo4j/001_schema.cypher ]; then
    cat migrations/neo4j/001_schema.cypher | docker compose exec -T neo4j cypher-shell 2>/dev/null && \
        echo "  ✅ Neo4j schema applied" || \
        echo "  ⚠️  Neo4j schema may already exist (OK)"
fi

# 4. Seed data (if available)
echo ""
echo "🌱 Seeding data..."
if command -v python &>/dev/null; then
    python scripts/seed_data.py 2>/dev/null && echo "  ✅ Seed data loaded" || echo "  ⚠️  Seed skipped (run manually: python scripts/seed_data.py)"
else
    echo "  ⚠️  Python not found, skip seeding. Run manually: python scripts/seed_data.py"
fi

# 5. Health check
echo ""
bash scripts/health-check.sh

echo ""
echo "🎉 Done! Run the app with: uvicorn src.main:app --reload --port 8000"
