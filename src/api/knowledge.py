"""Knowledge graph search API routes + Product knowledge base API."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Query

from src.db import neo4j as neo4j_db
from src.db import postgres as pg
from src.services.knowledge_service import get_knowledge_source_counts, list_faq_entries

from .schemas import APIResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)

_KB_ID_PATTERN = re.compile(r"(?:kb_)?(\d+)$")


def _parse_kb_id(raw_id: str) -> int | None:
    match = _KB_ID_PATTERN.search((raw_id or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


_POLICY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS policy_documents (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE,
    title TEXT,
    content TEXT,
    category TEXT,
    policy_type TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS policy_type TEXT;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
"""


async def _ensure_policy_documents_table() -> None:
    pool = pg.get_pool()
    if pool is None:
        raise RuntimeError("Database unavailable")
    async with pool.acquire() as conn:
        await conn.execute(_POLICY_TABLE_SQL)


# ── Product Knowledge Base (pgvector-based) ─────────────────────────


# UNUSED: no frontend caller
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
                """SELECT product_id, name, category, brand, description AS spec, retail_price, status
                   FROM products
                   WHERE (name ILIKE $1 OR category ILIKE $1 OR brand ILIKE $1 OR description ILIKE $1)
                   AND status = 'active'
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
                    "product_id": str(r["product_id"]),
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


# UNUSED: no frontend caller
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


# UNUSED: no frontend caller
@router.get("/v1/stats", response_model=APIResponse[dict])
async def knowledge_stats_v1() -> APIResponse[dict]:
    """GET /api/knowledge/v1/stats — 商品同步 + 知识库统计。"""
    pool = pg.get_pool()

    stats: dict = {}
    try:
        stats["source_products"] = await pool.fetchval("SELECT COUNT(*) FROM products")
        stats["source_with_images"] = await pool.fetchval(
            "SELECT COUNT(*) FROM products WHERE image_url IS NOT NULL AND image_url != ''"
        )
    except Exception:
        stats["source_products"] = 0
        stats["source_with_images"] = 0

    try:
        source_counts = await get_knowledge_source_counts(pool)
        stats.update(source_counts)
        stats["knowledge_total"] = source_counts.get("total_knowledge_items", 0)
        stats["with_embedding"] = 0
        stats["with_image_text"] = 0
        stats["search_mode"] = "sql_fulltext"
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


# UNUSED: no frontend caller
@router.get("/products", response_model=APIResponse[list[dict]])
async def list_knowledge_products(
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[list[dict]]:
    # Neo4j is not available, use products table as fallback
    try:
        pool = pg.get_pool()
        rows = await pool.fetch(
            """SELECT product_id as id, name, category, brand, description as description, retail_price, status
               FROM products
               WHERE status = 'active'
               ORDER BY retail_price DESC
               LIMIT $1""",
            limit,
        )
        return APIResponse(data=[dict(r) for r in rows])
    except Exception as e:
        logger.error(f"Failed to fetch products from products table: {e}")
        return APIResponse(data=[], message="Product database unavailable")


# UNUSED: no frontend caller
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


# UNUSED: no frontend caller
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
        pool = pg.get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO knowledge_base (
                category,
                subcategory,
                question,
                answer,
                keywords,
                priority,
                product_categories
            )
            VALUES (
                'faq',
                $1,
                $2,
                $3,
                $4,
                COALESCE($5, 10),
                $6
            )
            RETURNING id
            """,
            body.get("category", "通用"),
            body["question"],
            body["answer"],
            body.get("keywords") or [],
            body.get("priority"),
            body.get("product_categories") or [],
        )
        faq_id = f"kb_{row['id']}"
        return APIResponse(data={"faq_id": faq_id}, message="FAQ created")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.get("/faq", response_model=APIResponse[list[dict]])
async def list_faq(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    try:
        rows = await list_faq_entries(pool, category=category, limit=limit)
        return APIResponse(data=rows)
    except Exception as e:
        logger.error("Failed to list FAQ entries: %s", e)
        return APIResponse(success=False, data=[], message="FAQ database unavailable")


@router.put("/faq/{faq_id}", response_model=APIResponse[dict])
async def update_faq(faq_id: str, body: dict) -> APIResponse[dict]:
    try:
        kb_id = _parse_kb_id(faq_id)
        if kb_id is None:
            return APIResponse(success=False, message="Only knowledge_base FAQ entries are editable")
        pool = pg.get_pool()
        await pool.execute(
            """
            UPDATE knowledge_base
            SET subcategory = $2,
                question = $3,
                answer = $4,
                keywords = $5,
                priority = COALESCE($6, priority),
                product_categories = $7,
                updated_at = NOW()
            WHERE id = $1
            """,
            kb_id,
            body.get("category", "通用"),
            body["question"],
            body["answer"],
            body.get("keywords") or [],
            body.get("priority"),
            body.get("product_categories") or [],
        )
        return APIResponse(data={"faq_id": f"kb_{kb_id}"}, message="FAQ updated")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.delete("/faq/{faq_id}", response_model=APIResponse[dict])
async def delete_faq(faq_id: str) -> APIResponse[dict]:
    try:
        kb_id = _parse_kb_id(faq_id)
        if kb_id is None:
            return APIResponse(success=False, message="Only knowledge_base FAQ entries are deletable")
        pool = pg.get_pool()
        await pool.execute("DELETE FROM knowledge_base WHERE id = $1", kb_id)
        return APIResponse(data={"faq_id": f"kb_{kb_id}"}, message="FAQ deleted")
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.get("/policies", response_model=APIResponse[list[dict]])
async def list_policies(limit: int = Query(50, ge=1, le=200)) -> APIResponse[list[dict]]:
    try:
        await _ensure_policy_documents_table()
        pool = pg.get_pool()
        rows = await pool.fetch(
            """
            SELECT id, title, content, url, category, policy_type, fetched_at, updated_at
            FROM policy_documents
            ORDER BY updated_at DESC NULLS LAST, fetched_at DESC NULLS LAST, id DESC
            LIMIT $1
            """,
            limit,
        )
        return APIResponse(
            data=[
                {
                    "id": f"policy_{row['id']}",
                    "title": row["title"],
                    "content": row["content"],
                    "url": row["url"],
                    "category": row["category"] or row["policy_type"] or "售后政策",
                    "policy_type": row["policy_type"] or row["category"] or "售后政策",
                    "source": "policy_documents",
                }
                for row in rows
            ]
        )
    except Exception as exc:
        logger.error("Failed to list policy entries: %s", exc)
        return APIResponse(success=False, data=[], message="Policy database unavailable")


@router.post("/policies", response_model=APIResponse[dict])
async def add_policy(body: dict) -> APIResponse[dict]:
    try:
        await _ensure_policy_documents_table()
        pool = pg.get_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO policy_documents (url, title, content, category, policy_type, fetched_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            RETURNING id
            """,
            body.get("url"),
            body["title"],
            body["content"],
            body.get("category", "售后政策"),
            body.get("policy_type", body.get("category", "售后政策")),
        )
        return APIResponse(data={"policy_id": f"policy_{row['id']}"}, message="Policy created")
    except Exception as exc:
        logger.error("Failed to create policy: %s", exc)
        return APIResponse(success=False, data={}, message=str(exc))


@router.put("/policies/{policy_id}", response_model=APIResponse[dict])
async def update_policy(policy_id: str, body: dict) -> APIResponse[dict]:
    try:
        await _ensure_policy_documents_table()
        match = re.search(r"(?:policy_)?(\d+)$", (policy_id or "").strip())
        if not match:
            return APIResponse(success=False, data={}, message="Invalid policy id")
        row_id = int(match.group(1))
        pool = pg.get_pool()
        await pool.execute(
            """
            UPDATE policy_documents
            SET title = $2,
                content = $3,
                url = $4,
                category = $5,
                policy_type = $6,
                updated_at = NOW()
            WHERE id = $1
            """,
            row_id,
            body["title"],
            body["content"],
            body.get("url"),
            body.get("category", "售后政策"),
            body.get("policy_type", body.get("category", "售后政策")),
        )
        return APIResponse(data={"policy_id": f"policy_{row_id}"}, message="Policy updated")
    except Exception as exc:
        logger.error("Failed to update policy: %s", exc)
        return APIResponse(success=False, data={}, message=str(exc))


@router.delete("/policies/{policy_id}", response_model=APIResponse[dict])
async def delete_policy(policy_id: str) -> APIResponse[dict]:
    try:
        await _ensure_policy_documents_table()
        match = re.search(r"(?:policy_)?(\d+)$", (policy_id or "").strip())
        if not match:
            return APIResponse(success=False, data={}, message="Invalid policy id")
        row_id = int(match.group(1))
        pool = pg.get_pool()
        await pool.execute("DELETE FROM policy_documents WHERE id = $1", row_id)
        return APIResponse(data={"policy_id": f"policy_{row_id}"}, message="Policy deleted")
    except Exception as exc:
        logger.error("Failed to delete policy: %s", exc)
        return APIResponse(success=False, data={}, message=str(exc))


# UNUSED: no frontend caller
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
                """SELECT product_id, name, category, brand, description AS spec, retail_price
                   FROM products
                   WHERE (name ILIKE $1 OR category ILIKE $1 OR brand ILIKE $1)
                   AND status = 'active'
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


# ── Generate Product Knowledge (background task) ─────────────────────


@router.post("/generate-product-knowledge")
async def generate_product_knowledge(limit: int = 50):
    """Kick off scripts/generate_product_knowledge.py in the background and return immediately."""
    import asyncio
    import sys
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_product_knowledge.py"

    async def _run():
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(script_path), "--limit", str(limit),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as exc:
            logger.error("generate_product_knowledge failed: %s", exc)

    asyncio.create_task(_run())
    return APIResponse(data={"status": "started", "message": "已启动"})
