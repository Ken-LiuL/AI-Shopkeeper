"""Async Neo4j driver wrapper."""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from src.config import get_settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def init_driver() -> AsyncDriver:
    """Create and verify the global Neo4j async driver."""
    global _driver
    if _driver is not None:
        return _driver

    cfg = get_settings().system.database["neo4j"]
    _driver = AsyncGraphDatabase.driver(
        cfg["uri"],
        auth=(cfg["user"], cfg["password"]),
        max_connection_pool_size=cfg.get("max_connection_pool_size", 50),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j driver initialised (%s)", cfg["uri"])
    return _driver


def get_driver() -> AsyncDriver:
    """Return the current driver or raise if not initialised."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised. Call init_driver() first.")
    return _driver


async def close_driver() -> None:
    """Gracefully close the driver."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


async def query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    database: str | None = None,
) -> list[dict[str, Any]]:
    """Run a read query and return a list of record dicts."""
    driver = get_driver()
    db = database or get_settings().system.database["neo4j"].get("database", "neo4j")
    async with driver.session(database=db) as session:
        result = await session.run(cypher, parameters or {})
        records = await result.data()
        return records


async def execute_write(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    database: str | None = None,
) -> list[dict[str, Any]]:
    """Run a write query inside an implicit transaction."""
    driver = get_driver()
    db = database or get_settings().system.database["neo4j"].get("database", "neo4j")
    async with driver.session(database=db) as session:
        result = await session.run(cypher, parameters or {})
        records = await result.data()
        return records
