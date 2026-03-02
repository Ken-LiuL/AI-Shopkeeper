#!/usr/bin/env python3
"""Run pending migrations manually."""

import asyncio
import os

import asyncpg


async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    applied = {r["filename"] for r in await pool.fetch("SELECT filename FROM _migrations")}
    mdir = "/app/migrations/postgres"
    for fname in sorted(os.listdir(mdir)):
        if not fname.endswith(".sql") or fname in applied:
            continue
        print(f"Applying {fname}...")
        sql = open(f"{mdir}/{fname}").read()
        try:
            await pool.execute(sql)
            await pool.execute("INSERT INTO _migrations (filename) VALUES ($1)", fname)
            print("  OK")
        except Exception as e:
            print(f"  FAILED: {e}")
            break
    await pool.close()


asyncio.run(main())
