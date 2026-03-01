"""Knowledge graph search API routes + Product knowledge base API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Query

from src.db import neo4j as neo4j_db
from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


# ── Product Knowledge Base (pgvector-based) ─────────────────────────


@router.get("/v1/search", response_model=APIResponse[list[dict]])
async def search_product_knowledge_v1(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(5, ge=1, le=50),
    hybrid: bool = Query(True, description="是否使用混合检索"),
) -> APIResponse[list[dict]]:
    """GET /api/knowledge/v1/search — 语义搜索商品知识库。"""
    from src.agents.customer_service.skills_registry import get_product_knowledge

    pk = get_product_knowledge()
    if not pk:
        return APIResponse(success=False, data=[], message="Product knowledge not initialized")

    results = await pk.search_product(query=q, limit=limit, hybrid=hybrid)

    # Fallback: if knowledge base is empty, search products directly
    if not results:
        pool = pg.get_pool()
        try:
            # Search products by name/category/brand
            fallback_results = await pool.fetch(
                """SELECT spu_id, name, category, brand, spec, retail_price, status
                   FROM qnh_products
                   WHERE (name ILIKE $1 OR category ILIKE $1 OR brand ILIKE $1 OR spec ILIKE $1)
                   AND status = '在售'
                   ORDER BY
                     CASE WHEN name ILIKE $1 THEN 1
                          WHEN category ILIKE $1 THEN 2
                          WHEN brand ILIKE $1 THEN 3
                          ELSE 4 END,
                     retail_price DESC
                   LIMIT $2""",
                f"%{q}%",
                limit,
            )

            # Convert to knowledge format
            results = [
                {
                    "product_id": str(r["spu_id"]),
                    "name": r["name"],
                    "category": r.get("category", ""),
                    "brand": r.get("brand", ""),
                    "spec": r.get("spec", ""),
                    "price": float(r.get("retail_price", 0)),
                    "content": f"{r['name']} - {r.get('category', '')} - {r.get('brand', '')}",
                    "score": 0.8,  # Default relevance score
                    "source": "product_database",
                }
                for r in fallback_results
            ]
        except Exception as e:
            logger.error(f"Knowledge fallback search failed: {e}")

    return APIResponse(data=results)


@router.post("/v1/build", response_model=APIResponse[dict])
async def build_knowledge_v1(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(10, ge=1, le=100),
    extract_images: bool = Query(True),
    max_images: int = Query(3, ge=0, le=10),
    sync: bool = Query(False, description="同步执行（阻塞，适合调试）"),
) -> APIResponse[dict]:
    """POST /api/knowledge/v1/build — 触发知识库构建。

    默认异步执行，设 sync=true 可同步等待结果。
    """
    from src.agents.customer_service.skills_registry import get_product_knowledge

    pk = get_product_knowledge()
    if not pk:
        return APIResponse(success=False, data={}, message="Product knowledge not initialized")

    if sync:
        result = await pk.build_knowledge_base(
            batch_size=batch_size,
            extract_images=extract_images,
            max_images_per_product=max_images,
        )
        return APIResponse(data=result)
    else:
        background_tasks.add_task(
            pk.build_knowledge_base,
            batch_size=batch_size,
            extract_images=extract_images,
            max_images_per_product=max_images,
        )
        return APIResponse(data={"status": "building", "message": "知识库构建已在后台启动"})


@router.get("/v1/stats", response_model=APIResponse[dict])
async def knowledge_stats_v1() -> APIResponse[dict]:
    """GET /api/knowledge/v1/stats — 商品同步 + 知识库统计。"""
    pool = pg.get_pool()

    stats: dict = {}
    try:
        stats["source_products"] = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
        stats["source_with_images"] = await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_products WHERE image_url IS NOT NULL AND image_url != ''"
        )
    except Exception:
        stats["source_products"] = 0
        stats["source_with_images"] = 0

    try:
        stats["knowledge_total"] = stats.get("source_products", 0)
        stats["with_embedding"] = 0
        stats["search_mode"] = "sql_fulltext"

        with_image_text = 0
        if False:  # Chroma disabled
            all_meta = {}  # type: ignore[assignment]
            with_image_text = sum(
                1 for m in (all_meta.get("metadatas") or []) if m.get("image_text", "").strip()
            )
        stats["with_image_text"] = with_image_text
    except Exception:
        stats["knowledge_total"] = 0
        stats["with_embedding"] = 0
        stats["with_image_text"] = 0

    try:
        sync_row = await pool.fetchrow("SELECT * FROM sync_state WHERE syncer_name = 'products'")
        if sync_row:
            stats["last_sync"] = {
                "status": sync_row["last_sync_status"],
                "records": sync_row["records_synced"],
                "duration_ms": sync_row["last_sync_duration_ms"],
                "last_full": str(sync_row["last_full_sync"])
                if sync_row["last_full_sync"]
                else None,
                "error": sync_row["last_sync_error"],
            }
    except Exception:
        pass

    return APIResponse(data=stats)


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

    # Final fallback: search products in PostgreSQL if Neo4j returned nothing
    if not results:
        try:
            pool = pg.get_pool()
            rows = await pool.fetch(
                """SELECT spu_id, name, category, brand, spec, retail_price
                   FROM qnh_products
                   WHERE (name ILIKE $1 OR category ILIKE $1 OR brand ILIKE $1)
                   AND status = '在售'
                   ORDER BY retail_price DESC
                   LIMIT $2""",
                f"%{q}%",
                limit,
            )
            results.extend(
                {
                    "name": r["name"],
                    "description": f"{r.get('brand', '')} {r.get('spec', '')} ¥{r.get('retail_price', 0)}",
                    "category": r.get("category", ""),
                    "source": "product_database",
                }
                for r in rows
            )
        except Exception:
            logger.debug("Postgres product search fallback failed", exc_info=True)

    return APIResponse(data=results)
