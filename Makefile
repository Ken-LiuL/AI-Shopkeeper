.PHONY: setup dev test lint seed migrate-pg migrate-neo4j docker-build docker-up

setup:
	pip install -e ".[dev]"

dev:
	docker compose up -d postgres neo4j redis
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -v --tb=short

lint:
	ruff check src tests
	mypy src

seed:
	python scripts/seed_data.py

migrate-pg:
	python scripts/migrate.py --postgres-only

migrate-neo4j:
	python scripts/migrate.py --neo4j-only

docker-build:
	docker build -t ai-store-manager:latest .

docker-up:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
