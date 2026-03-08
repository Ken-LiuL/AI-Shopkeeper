"""Chroma vector store — lightweight embedded vector DB for product knowledge.

Persists to /app/data/chroma (Fly volume) if available, else /tmp/chroma.
Falls back to in-memory if persistence fails.
"""

from __future__ import annotations

import logging
from pathlib import Path

import chromadb

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None

COLLECTION_NAME = "product_knowledge"


def _resolve_persist_path() -> str | None:
    """Pick persistence directory, return None for in-memory mode."""
    for candidate in ("/app/data/chroma", "/tmp/chroma"):
        p = Path(candidate)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return str(p)
        except Exception:
            continue
    return None


def get_client() -> chromadb.ClientAPI | None:
    """Get or create the singleton Chroma client.

    Returns None if ChromaDB is unavailable (instead of raising).
    """
    global _client
    if _client is None:
        try:
            persist_path = _resolve_persist_path()
            if persist_path:
                logger.info("Chroma persistent storage: %s", persist_path)
                _client = chromadb.PersistentClient(path=persist_path)
            else:
                logger.warning("Chroma using in-memory mode (no writable path)")
                _client = chromadb.EphemeralClient()
        except Exception as exc:
            logger.error("ChromaDB client init failed: %s — vector search unavailable", exc, exc_info=True)
            return None
    return _client


def get_collection() -> chromadb.Collection | None:
    """Get or create the product_knowledge collection.

    Returns None if ChromaDB is unavailable (instead of raising).
    """
    client = get_client()
    if client is None:
        return None
    try:
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as exc:
        logger.error("ChromaDB get_collection failed: %s", exc, exc_info=True)
        return None
