"""Knowledge graph search API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.db import neo4j as neo4j_db

from .schemas import APIResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


@router.get("/search", response_model=APIResponse[list[dict]])
async def search_knowledge(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
) -> APIResponse[list[dict]]:
    """Search the knowledge graph for FAQ answers, product info, and related entities.

    Used by the customer service agent to find relevant knowledge.
    """
    results: list[dict] = []

    try:
        # Search FAQ nodes
        faq_results = await neo4j_db.query(
            """MATCH (f:FAQ)
               WHERE f.question CONTAINS $q OR f.answer CONTAINS $q
               RETURN f.question AS question, f.answer AS answer, f.category AS category,
                      'faq' AS source
               LIMIT $limit""",
            {"q": q, "limit": limit},
        )
        results.extend(faq_results)
    except Exception:
        logger.debug("FAQ search failed", exc_info=True)

    try:
        # Search product knowledge nodes
        product_results = await neo4j_db.query(
            """MATCH (p:Product)
               WHERE p.name CONTAINS $q OR p.description CONTAINS $q
               OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
               RETURN p.name AS name, p.description AS description,
                      c.name AS category, 'product' AS source
               LIMIT $limit""",
            {"q": q, "limit": limit},
        )
        results.extend(product_results)
    except Exception:
        logger.debug("Product knowledge search failed", exc_info=True)

    try:
        # Full-text search fallback across all nodes with name property
        if not results:
            fallback = await neo4j_db.query(
                """MATCH (n)
                   WHERE any(prop IN keys(n) WHERE toString(n[prop]) CONTAINS $q)
                   RETURN labels(n) AS labels, properties(n) AS props, 'graph' AS source
                   LIMIT $limit""",
                {"q": q, "limit": limit},
            )
            results.extend(fallback)
    except Exception:
        logger.debug("Fallback search failed", exc_info=True)

    return APIResponse(data=results)
