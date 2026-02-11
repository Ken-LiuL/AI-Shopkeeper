#!/usr/bin/env bash
set -uo pipefail

echo "🏥 Health Check - AI Store Manager Infrastructure"
echo "================================================="

STATUS=0

# PostgreSQL
if docker compose ps postgres 2>/dev/null | grep -q "healthy"; then
    echo "  ✅ PostgreSQL  — healthy (port 5432)"
elif pg_isready -h localhost -p 5432 -U postgres &>/dev/null; then
    echo "  ✅ PostgreSQL  — reachable (port 5432)"
else
    echo "  ❌ PostgreSQL  — not reachable"
    STATUS=1
fi

# Neo4j
if docker compose ps neo4j 2>/dev/null | grep -q "healthy"; then
    echo "  ✅ Neo4j       — healthy (port 7474/7687)"
elif curl -sf http://localhost:7474 &>/dev/null; then
    echo "  ✅ Neo4j       — reachable (port 7474)"
else
    echo "  ❌ Neo4j       — not reachable"
    STATUS=1
fi

# Redis
if docker compose ps redis 2>/dev/null | grep -q "healthy"; then
    echo "  ✅ Redis       — healthy (port 6379)"
elif redis-cli -h localhost -p 6379 ping 2>/dev/null | grep -q PONG; then
    echo "  ✅ Redis       — reachable (port 6379)"
else
    echo "  ❌ Redis       — not reachable"
    STATUS=1
fi

echo ""
if [ $STATUS -eq 0 ]; then
    echo "✅ All services healthy!"
else
    echo "⚠️  Some services are down. Run: docker compose up -d"
fi

exit $STATUS
