"""Knowledge graph search API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.db import neo4j as neo4j_db

from .schemas import APIResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


@router.get("/products", response_model=APIResponse[list[dict]])
async def list_knowledge_products(
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[list[dict]]:
    try:
        rows = await neo4j_db.query(
            "MATCH (p:Product) RETURN p.id AS id, p.name AS name, p.category AS category, p.description AS description LIMIT $limit",
            {"limit": limit},
        )
        return APIResponse(data=rows)
    except Exception:
        return APIResponse(data=[], message="Knowledge graph unavailable")


@router.post("/products", response_model=APIResponse[dict])
async def add_knowledge_product(body: dict) -> APIResponse[dict]:
    try:
        await neo4j_db.query(
            """MERGE (p:Product {id: $id})
               SET p.name = $name, p.category = $category, p.description = $description""",
            body,
        )
        return APIResponse(data=body, message="Product added to knowledge graph")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.get("/products/{product_id}/graph", response_model=APIResponse[dict])
async def product_graph(product_id: str) -> APIResponse[dict]:
    try:
        nodes = await neo4j_db.query(
            """MATCH (p:Product {id: $id})-[r]-(n)
               RETURN p.name AS source, type(r) AS relation, labels(n) AS target_labels,
                      properties(n) AS target_props LIMIT 50""",
            {"id": product_id},
        )
        return APIResponse(data={"product_id": product_id, "relations": nodes})
    except Exception:
        return APIResponse(data={"product_id": product_id, "relations": []})


@router.post("/faq", response_model=APIResponse[dict])
async def add_faq(body: dict) -> APIResponse[dict]:
    try:
        import uuid

        faq_id = f"faq_{uuid.uuid4().hex[:12]}"
        await neo4j_db.query(
            """CREATE (f:FAQ {id: $id, question: $question, answer: $answer, category: $category})""",
            {
                "id": faq_id,
                "question": body["question"],
                "answer": body["answer"],
                "category": body.get("category", "general"),
            },
        )
        return APIResponse(data={"faq_id": faq_id}, message="FAQ created")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.get("/faq", response_model=APIResponse[list[dict]])
async def list_faq(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[list[dict]]:
    try:
        if category:
            rows = await neo4j_db.query(
                "MATCH (f:FAQ) WHERE f.category = $cat RETURN f.id AS id, f.question AS question, f.answer AS answer, f.category AS category LIMIT $limit",
                {"cat": category, "limit": limit},
            )
        else:
            rows = await neo4j_db.query(
                "MATCH (f:FAQ) RETURN f.id AS id, f.question AS question, f.answer AS answer, f.category AS category LIMIT $limit",
                {"limit": limit},
            )
        return APIResponse(data=rows)
    except Exception:
        return APIResponse(data=[])


@router.put("/faq/{faq_id}", response_model=APIResponse[dict])
async def update_faq(faq_id: str, body: dict) -> APIResponse[dict]:
    try:
        await neo4j_db.query(
            """MATCH (f:FAQ {id: $id}) SET f.question = $question, f.answer = $answer, f.category = $category""",
            {
                "id": faq_id,
                "question": body["question"],
                "answer": body["answer"],
                "category": body.get("category", "general"),
            },
        )
        return APIResponse(data={"faq_id": faq_id}, message="FAQ updated")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.delete("/faq/{faq_id}", response_model=APIResponse[dict])
async def delete_faq(faq_id: str) -> APIResponse[dict]:
    try:
        await neo4j_db.query("MATCH (f:FAQ {id: $id}) DELETE f", {"id": faq_id})
        return APIResponse(data={"faq_id": faq_id}, message="FAQ deleted")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


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
