#!/usr/bin/env python3
"""数据库迁移脚本 — 按序号执行 PostgreSQL / Neo4j migrations"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os

import asyncpg
from neo4j import AsyncGraphDatabase


async def ensure_migration_table(conn: asyncpg.Connection):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_history (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


async def get_applied(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT filename FROM migration_history")
    return {r["filename"] for r in rows}


async def run_postgres_migrations(dsn: str, migrations_dir: str):
    conn = await asyncpg.connect(dsn)
    try:
        await ensure_migration_table(conn)
        applied = await get_applied(conn)

        files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
        for fpath in files:
            fname = os.path.basename(fpath)
            if fname in applied:
                print(f"  [skip] {fname}")
                continue
            print(f"  [run]  {fname}")
            sql = open(fpath).read()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO migration_history (filename) VALUES ($1)", fname)
    finally:
        await conn.close()


async def run_neo4j_migrations(uri: str, auth: tuple[str, str], migrations_dir: str):
    driver = AsyncGraphDatabase.driver(uri, auth=auth)
    async with driver:
        # 用 neo4j 自身记录已执行 (constraint node)
        async with driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Migration) REQUIRE m.filename IS UNIQUE"
            )

            files = sorted(glob.glob(os.path.join(migrations_dir, "*.cypher")))
            for fpath in files:
                fname = os.path.basename(fpath)
                result = await session.run("MATCH (m:Migration {filename: $f}) RETURN m", f=fname)
                if await result.single():
                    print(f"  [skip] {fname}")
                    continue
                print(f"  [run]  {fname}")
                cypher = open(fpath).read()
                for stmt in cypher.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await session.run(stmt)
                await session.run(
                    "CREATE (m:Migration {filename: $f, applied_at: datetime()})", f=fname
                )


async def main():
    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("--postgres-only", action="store_true")
    parser.add_argument("--neo4j-only", action="store_true")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_pg = not args.neo4j_only
    run_neo = not args.postgres_only

    if run_pg:
        dsn = os.environ.get(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_store_manager"
        )
        print("=== PostgreSQL Migrations ===")
        await run_postgres_migrations(dsn, os.path.join(base, "migrations", "postgres"))

    if run_neo:
        neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        neo4j_pass = os.environ.get("NEO4J_PASSWORD", "password")
        print("=== Neo4j Migrations ===")
        await run_neo4j_migrations(
            neo4j_uri, (neo4j_user, neo4j_pass), os.path.join(base, "migrations", "neo4j")
        )

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
