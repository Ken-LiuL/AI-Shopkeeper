#!/usr/bin/env python3
"""
Build embeddings for all Product nodes in Neo4j.

Reads Product nodes without embedding, generates text embeddings via OpenRouter,
and writes them back to Neo4j for use with the vector index.

Usage (inside aishop-app container):
    python3 scripts/build_neo4j_embeddings.py
"""

from __future__ import annotations

import os
import sys
import time
import logging

from neo4j import GraphDatabase
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "aishop2026neo4j")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

BATCH_SIZE = 50  # Products per embedding API call


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Call OpenRouter embedding API for a batch of texts."""
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    sorted_data = sorted(resp.data, key=lambda x: x.index)
    return [d.embedding for d in sorted_data]


def main() -> None:
    print("=" * 60)
    print("Neo4j Product Embedding Builder")
    print("=" * 60)

    if not OPENROUTER_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    # ── Connect ────────────────────────────────────────────────────────
    print(f"\nConnecting to Neo4j: {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    client = OpenAI(base_url=OPENROUTER_BASE, api_key=OPENROUTER_KEY)

    try:
        with driver.session() as session:
            # Count products without embeddings
            r = session.run(
                "MATCH (n:Product) WHERE n.embedding IS NULL RETURN count(n) AS cnt"
            ).single()
            no_emb = r["cnt"] if r else 0

            r = session.run("MATCH (n:Product) RETURN count(n) AS cnt").single()
            total = r["cnt"] if r else 0

            print(f"Total Product nodes: {total}")
            print(f"Without embeddings:  {no_emb}")

            if no_emb == 0:
                print("\n✅ All products already have embeddings!")
                return

            print(f"\nBuilding embeddings for {no_emb} products (batch={BATCH_SIZE})...")

            # Fetch all products without embeddings
            result = session.run(
                """
                MATCH (n:Product) WHERE n.embedding IS NULL
                RETURN n.product_id AS product_id, n.name AS name,
                       n.category AS category, n.brand AS brand,
                       n.description AS description
                """
            )
            products = result.data()

            updated = 0
            errors = 0
            start_time = time.time()

            for i in range(0, len(products), BATCH_SIZE):
                chunk = products[i : i + BATCH_SIZE]

                # Build text for embedding
                texts = []
                for p in chunk:
                    text = " ".join(
                        filter(
                            None,
                            [
                                p.get("name") or "",
                                p.get("brand") or "",
                                p.get("category") or "",
                                (p.get("description") or "")[:100],  # truncate long desc
                            ],
                        )
                    )
                    texts.append(text or "未知商品")

                try:
                    embeddings = embed_batch(client, texts)
                except Exception as e:
                    logger.error("Embedding batch %d-%d failed: %s", i, i + len(chunk), e)
                    errors += len(chunk)
                    continue

                # Write embeddings back to Neo4j
                for prod, embedding in zip(chunk, embeddings):
                    try:
                        session.run(
                            """
                            MATCH (n:Product {product_id: $product_id})
                            SET n.embedding = $embedding
                            """,
                            product_id=prod["product_id"],
                            embedding=embedding,
                        )
                        updated += 1
                    except Exception as e:
                        logger.error("Write embedding failed for %s: %s", prod["product_id"], e)
                        errors += 1

                elapsed = time.time() - start_time
                done = min(i + BATCH_SIZE, len(products))
                pct = done / len(products) * 100
                print(
                    f"  Progress: {done}/{len(products)} ({pct:.1f}%) | "
                    f"Updated: {updated} | Errors: {errors} | {elapsed:.1f}s"
                )

            print(f"\n✓ Embedding build complete: {updated} updated, {errors} errors")

            # Final count
            r = session.run(
                "MATCH (n:Product) WHERE n.embedding IS NOT NULL RETURN count(n) AS cnt"
            ).single()
            with_emb = r["cnt"] if r else 0
            print(f"  Products with embeddings: {with_emb}/{total}")

    finally:
        driver.close()

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
