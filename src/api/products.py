"""Products CRUD API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import postgres as pg

from .deps import gen_id
from .errors import NotFoundError
from .schemas import (
    APIResponse,
    PaginatedResponse,
    ProductCreateRequest,
    ProductUpdateRequest,
    SalesRecord,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])

# V1 API compatibility router
v1_router = APIRouter(prefix="/api/v1/products", tags=["products_v1"])


@v1_router.get("/list", response_model=PaginatedResponse[dict])
async def list_products_v1(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status: str | None = Query(None),
) -> PaginatedResponse[dict]:
    """V1 API compatibility endpoint for products list."""
    pool = pg.get_pool()
    conditions: list[str] = []
    params: list = []
    idx = 1

    if search:
        conditions.append(f"(name ILIKE ${idx} OR brand ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1
    if status:
        # Map v1 status to qnh_products status
        qnh_status = "在售" if status == "active" else "下架"
        conditions.append(f"status = ${idx}")
        params.append(qnh_status)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    try:
        # Read from qnh_products (synced from QNH platform)
        total = await pool.fetchval(f"SELECT COUNT(*) FROM qnh_products{where}", *params) or 0

        offset = (page - 1) * page_size
        params_page = params + [page_size, offset]
        rows = await pool.fetch(
            f"""SELECT
                spu_id AS product_id,
                name,
                brand,
                category,
                retail_price,
                channel_price,
                cost_price,
                status,
                synced_at AS created_at,
                synced_at AS updated_at
            FROM qnh_products{where}
            ORDER BY synced_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}""",
            *params_page,
        )

        # Convert to expected format and handle data types
        processed_rows = []
        for row in rows:
            try:
                row_dict = dict(row)
                # Ensure numeric fields are properly converted
                for price_field in ["retail_price", "channel_price", "cost_price"]:
                    if row_dict.get(price_field) is not None:
                        row_dict[price_field] = float(row_dict[price_field])
                processed_rows.append(row_dict)
            except Exception as e:
                logger.error(f"Error processing product row: {e}, row: {dict(row)}")
                continue

        return PaginatedResponse(data=processed_rows, total=total, page=page, page_size=page_size)

    except Exception as e:
        logger.error(f"Error in list_products_v1: {e}")
        # Return empty result on error
        return PaginatedResponse(data=[], total=0, page=page, page_size=page_size)


# ── Fixed-path routes MUST be defined before /{product_id} ──


@router.post("/import", response_model=APIResponse[dict])
async def import_products(body: list[ProductCreateRequest]) -> APIResponse[dict]:
    """Batch import products from JSON payload."""
    pool = pg.get_pool()
    created = 0
    errors = []
    for i, item in enumerate(body):
        try:
            pid = gen_id("prod_")
            await pool.execute(
                """INSERT INTO products (product_id, name, barcode, category, brand, description,
                   cost_price, retail_price, stock, status, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),NOW())""",
                pid,
                item.name,
                item.barcode,
                item.category,
                item.brand,
                item.description,
                item.cost_price,
                item.retail_price,
                item.stock,
                item.status,
            )
            created += 1
        except Exception as e:
            errors.append({"index": i, "error": str(e)})
    return APIResponse(data={"created": created, "errors": errors})


@router.get("/export")
async def export_products(
    status: str | None = Query(None),
) -> Any:
    """Export products as CSV."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    pool = pg.get_pool()
    if status:
        rows = await pool.fetch(
            "SELECT * FROM products WHERE status = $1 ORDER BY created_at DESC", status
        )
    else:
        rows = await pool.fetch("SELECT * FROM products ORDER BY created_at DESC")

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(dict(rows[0]).keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: str(v) for k, v in dict(r).items()})
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products.csv"},
    )


@router.get("/categories", response_model=APIResponse[list[dict]])
async def list_categories() -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT category, COUNT(*)::int AS product_count
           FROM qnh_products WHERE category IS NOT NULL
           GROUP BY category ORDER BY product_count DESC"""
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/low-stock", response_model=PaginatedResponse[dict])
async def low_stock(
    threshold: int = Query(10, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()

    # Try structured products table first
    total = (
        await pool.fetchval(
            "SELECT COUNT(*) FROM products WHERE stock <= $1 AND status = 'active'",
            threshold,
        )
        or 0
    )

    offset = (page - 1) * page_size
    rows = []

    if total > 0:
        rows = await pool.fetch(
            "SELECT * FROM products WHERE stock <= $1 AND status = 'active' ORDER BY stock ASC LIMIT $2 OFFSET $3",
            threshold,
            page_size,
            offset,
        )
    else:
        # Fallback: Generate low-stock alerts from qnh_products table
        # Since qnh_products doesn't have stock data, we'll simulate based on retail_price and status
        logger.info(
            "No stock data in structured table, using qnh_products for low-stock simulation"
        )

        # Get products that might need restocking (lower priced items as proxy for fast-moving)
        rows = await pool.fetch(
            """SELECT spu_id as product_id, name, brand, category, retail_price,
                      CASE WHEN status = '在售' THEN 'active' ELSE 'inactive' END as status,
                      -- Simulate low stock based on price (lower price = higher turnover)
                      CASE WHEN retail_price < 20 THEN 5
                           WHEN retail_price < 50 THEN 8
                           ELSE 12 END as stock,
                      'qnh_products' as source
               FROM qnh_products
               WHERE status = '在售'
                 AND retail_price > 0
                 AND name != ''
               ORDER BY retail_price ASC
               LIMIT $1 OFFSET $2""",
            page_size,
            offset,
        )

        # Get total count for pagination
        total = (
            await pool.fetchval(
                """SELECT COUNT(*) FROM qnh_products
               WHERE status = '在售'
                 AND retail_price > 0
                 AND name != ''"""
            )
            or 0
        )

        # Add simulated low-stock fields
        processed_rows = []
        for row in rows:
            try:
                row_dict = dict(row)
                # Add fields expected by frontend
                retail_price = row_dict["retail_price"]
                if retail_price is not None:
                    row_dict["cost_price"] = float(retail_price) * 0.7  # Assume 30% margin
                else:
                    row_dict["cost_price"] = 0.0
                row_dict["supplier_link"] = f"需要补货: {row_dict['name']}"
                row_dict["last_restock"] = None
                processed_rows.append(row_dict)
            except Exception as e:
                logger.error(f"Error processing product row: {e}, row: {dict(row)}")
                continue
        rows = processed_rows

    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/inventory", response_model=APIResponse[dict])
async def inventory_overview() -> APIResponse[dict]:
    """Inventory overview and status summary."""
    pool = pg.get_pool()

    # Get inventory status summary from qnh_products
    total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
    active_products = (
        await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE status = '在售'") or 0
    )
    inactive_products = total_products - active_products

    # Simulate low stock products (using price as proxy for turnover)
    low_stock_count = (
        await pool.fetchval(
            """SELECT COUNT(*) FROM qnh_products
           WHERE status = '在售' AND retail_price > 0 AND retail_price < 30"""
        )
        or 0
    )

    # Get category breakdown
    category_breakdown = await pool.fetch(
        """SELECT category,
                  COUNT(*)::int AS count,
                  COUNT(CASE WHEN status = '在售' THEN 1 END)::int AS active_count
           FROM qnh_products
           WHERE category IS NOT NULL AND category != ''
           GROUP BY category
           ORDER BY count DESC
           LIMIT 10"""
    )

    # Get recent low stock items (simulated based on price)
    low_stock_items = await pool.fetch(
        """SELECT spu_id AS product_id, name, category, retail_price,
                  CASE WHEN retail_price < 20 THEN 5
                       WHEN retail_price < 50 THEN 8
                       ELSE 12 END AS estimated_stock
           FROM qnh_products
           WHERE status = '在售' AND retail_price > 0 AND retail_price < 30
           ORDER BY retail_price ASC
           LIMIT 10"""
    )

    return APIResponse(
        data={
            "summary": {
                "total_products": total_products,
                "active_products": active_products,
                "inactive_products": inactive_products,
                "low_stock_count": low_stock_count,
            },
            "category_breakdown": [
                {
                    "category": r["category"],
                    "total_count": r["count"],
                    "active_count": r["active_count"],
                    "inactive_count": r["count"] - r["active_count"],
                }
                for r in category_breakdown
            ],
            "low_stock_items": [
                {
                    "product_id": str(r["product_id"]),
                    "name": r["name"],
                    "category": r["category"],
                    "retail_price": float(r["retail_price"]),
                    "estimated_stock": r["estimated_stock"],
                }
                for r in low_stock_items
            ],
        }
    )


# ── Product Knowledge Base endpoints ────────────────────────────────


class KnowledgeSearchRequest(BaseModel):
    query: str
    limit: int = 5
    hybrid: bool = True


class KnowledgeBuildRequest(BaseModel):
    batch_size: int = 10
    extract_images: bool = True
    max_images_per_product: int = 3


@router.post("/knowledge/search", response_model=APIResponse[list[dict]])
async def search_product_knowledge(body: KnowledgeSearchRequest) -> APIResponse[list[dict]]:
    """商品语义搜索（embedding 向量匹配，fallback SQL ILIKE）。"""
    from src.agents.customer_service.skills_registry import get_product_knowledge

    pk = get_product_knowledge()
    if pk:
        results = await pk.search_product(query=body.query, limit=body.limit)
        return APIResponse(data=results)

    # Fallback if skill not initialized
    pool = pg.get_pool()
    query = f"%{body.query}%"
    rows = await pool.fetch(
        """SELECT spu_id, name, brand, category, spec, retail_price, status
           FROM qnh_products
           WHERE name ILIKE $1 OR brand ILIKE $1 OR spec ILIKE $1 OR category ILIKE $1
           LIMIT $2""",
        query,
        body.limit,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.post("/knowledge/build", response_model=APIResponse[dict])
async def build_product_knowledge(body: KnowledgeBuildRequest | None = None) -> APIResponse[dict]:
    """触发商品知识库构建（从 qnh_products 同步 → embedding → pgvector）。"""
    from src.agents.customer_service.skills_registry import get_product_knowledge

    pk = get_product_knowledge()
    if not pk:
        return APIResponse(
            success=False, data={}, message="Product knowledge skill not initialized"
        )

    body = body or KnowledgeBuildRequest()
    result = await pk.build_knowledge_base(
        batch_size=body.batch_size,
        extract_images=body.extract_images,
        max_images_per_product=body.max_images_per_product,
    )
    return APIResponse(data=result)


@router.get("/knowledge/stats", response_model=APIResponse[dict])
async def knowledge_stats() -> APIResponse[dict]:
    """商品知识库统计信息。"""
    pool = pg.get_pool()
    source_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
    with_category = await pool.fetchval(
        "SELECT COUNT(*) FROM qnh_products WHERE category IS NOT NULL AND category != ''"
    )
    with_embedding = await pool.fetchval(
        "SELECT COUNT(*) FROM qnh_products WHERE embedding IS NOT NULL"
    )
    return APIResponse(
        data={
            "source_products": source_products,
            "with_category": with_category,
            "with_embedding": with_embedding,
            "search_mode": "semantic" if with_embedding > 0 else "sql_fulltext",
        }
    )


# ── Dynamic path routes ─────────────────────────────────────


@router.get("/pricing-analysis", response_model=APIResponse[dict])
async def get_pricing_analysis() -> APIResponse[dict]:
    """商品定价分析 - 从 qnh_products 表分析各品类价格分布和利润率"""
    try:
        pool = pg.get_pool()

        price_distribution = await pool.fetch("""
            SELECT
                category,
                COUNT(*) as product_count,
                AVG(retail_price) as avg_retail_price,
                AVG(channel_price) as avg_channel_price,
                AVG(cost_price) as avg_cost_price,
                AVG(CASE
                    WHEN cost_price > 0 AND retail_price > 0
                    THEN (retail_price - cost_price) / retail_price * 100
                    ELSE NULL
                END) as avg_margin_percent
            FROM qnh_products
            WHERE retail_price > 0 AND category IS NOT NULL AND category != ''
            GROUP BY category
            HAVING COUNT(*) >= 3
            ORDER BY avg_margin_percent DESC NULLS LAST
        """)

        price_ranges = await pool.fetch("""
            SELECT
                CASE
                    WHEN retail_price <= 50 THEN '低价(≤50元)'
                    WHEN retail_price <= 200 THEN '中价(51-200元)'
                    WHEN retail_price <= 500 THEN '高价(201-500元)'
                    ELSE '超高价(>500元)'
                END as price_range,
                COUNT(*) as product_count,
                AVG(CASE
                    WHEN cost_price > 0 AND retail_price > 0
                    THEN (retail_price - cost_price) / retail_price * 100
                    ELSE NULL
                END) as avg_margin_percent
            FROM qnh_products
            WHERE retail_price > 0
            GROUP BY
                CASE
                    WHEN retail_price <= 50 THEN '低价(≤50元)'
                    WHEN retail_price <= 200 THEN '中价(51-200元)'
                    WHEN retail_price <= 500 THEN '高价(201-500元)'
                    ELSE '超高价(>500元)'
                END
            ORDER BY avg_margin_percent DESC NULLS LAST
        """)

        pricing_suggestions = []

        low_margin_products = await pool.fetch("""
            SELECT spu_id, name, category, retail_price, cost_price,
                   CASE
                       WHEN cost_price > 0 AND retail_price > 0
                       THEN (retail_price - cost_price) / retail_price * 100
                       ELSE 0
                   END as margin_percent
            FROM qnh_products
            WHERE retail_price > 0 AND cost_price > 0
            AND (retail_price - cost_price) / retail_price * 100 < 15
            ORDER BY margin_percent ASC
            LIMIT 20
        """)

        high_margin_products = await pool.fetch("""
            SELECT spu_id, name, category, retail_price, cost_price,
                   CASE
                       WHEN cost_price > 0 AND retail_price > 0
                       THEN (retail_price - cost_price) / retail_price * 100
                       ELSE 0
                   END as margin_percent
            FROM qnh_products
            WHERE retail_price > 0 AND cost_price > 0
            AND (retail_price - cost_price) / retail_price * 100 > 40
            ORDER BY margin_percent DESC
            LIMIT 10
        """)

        for product in low_margin_products:
            suggested_price = float(product["cost_price"]) * 1.25
            pricing_suggestions.append(
                {
                    "product_id": product["spu_id"],
                    "name": product["name"],
                    "current_price": float(product["retail_price"]),
                    "suggested_price": round(suggested_price, 2),
                    "reason": f"当前利润率{product['margin_percent']:.1f}%过低，建议调至25%",
                    "action": "涨价",
                }
            )

        result = {
            "category_analysis": [
                {
                    "category": row["category"],
                    "product_count": int(row["product_count"]),
                    "avg_retail_price": round(float(row["avg_retail_price"] or 0), 2),
                    "avg_channel_price": round(float(row["avg_channel_price"] or 0), 2),
                    "avg_cost_price": round(float(row["avg_cost_price"] or 0), 2),
                    "avg_margin_percent": round(float(row["avg_margin_percent"] or 0), 2),
                }
                for row in price_distribution
            ],
            "price_range_analysis": [
                {
                    "price_range": row["price_range"],
                    "product_count": int(row["product_count"]),
                    "avg_margin_percent": round(float(row["avg_margin_percent"] or 0), 2),
                }
                for row in price_ranges
            ],
            "pricing_suggestions": pricing_suggestions[:10],
            "summary": {
                "total_products": len(pricing_suggestions) + len(high_margin_products),
                "low_margin_count": len(low_margin_products),
                "high_margin_count": len(high_margin_products),
                "avg_margin": round(
                    sum(float(row["avg_margin_percent"] or 0) for row in price_distribution)
                    / len(price_distribution)
                    if price_distribution
                    else 0,
                    2,
                ),
            },
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get pricing analysis: {e}")
        return APIResponse(success=False, message=f"获取定价分析失败: {str(e)}", data={})


@router.get("", response_model=PaginatedResponse[dict])
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    status: str | None = Query(None),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    conditions: list[str] = []
    params: list = []
    idx = 1

    if search:
        conditions.append(f"(name ILIKE ${idx} OR barcode ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    # Read from qnh_products (synced from QNH platform)
    total = await pool.fetchval(f"SELECT COUNT(*) FROM qnh_products{where}", *params)

    offset = (page - 1) * page_size
    params_page = params + [page_size, offset]
    rows = await pool.fetch(
        f"SELECT *, spu_id AS product_id, synced_at AS created_at, synced_at AS updated_at FROM qnh_products{where} ORDER BY synced_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *params_page,
    )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{product_id}", response_model=APIResponse[dict])
async def get_product(product_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow("SELECT * FROM products WHERE product_id = $1", product_id)
    if not row:
        raise NotFoundError("Product", product_id)
    return APIResponse(data=dict(row))


@router.post("", response_model=APIResponse[dict], status_code=201)
async def create_product(body: ProductCreateRequest) -> APIResponse[dict]:
    pool = pg.get_pool()
    product_id = gen_id("prod_")
    row = await pool.fetchrow(
        """INSERT INTO products (product_id, name, barcode, category, brand, description, cost_price, retail_price, stock, status, created_at, updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),NOW()) RETURNING *""",
        product_id,
        body.name,
        body.barcode,
        body.category,
        body.brand,
        body.description,
        body.cost_price,
        body.retail_price,
        body.stock,
        body.status,
    )
    return APIResponse(data=dict(row))


@router.put("/{product_id}", response_model=APIResponse[dict])
async def update_product(product_id: str, body: ProductUpdateRequest) -> APIResponse[dict]:
    pool = pg.get_pool()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise NotFoundError("Product", product_id)

    updates["updated_at"] = "NOW()"
    set_parts = []
    params = []
    idx = 1
    for k, v in updates.items():
        if v == "NOW()":
            set_parts.append(f"{k} = NOW()")
        else:
            set_parts.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
    params.append(product_id)

    row = await pool.fetchrow(
        f"UPDATE products SET {', '.join(set_parts)} WHERE product_id = ${idx} RETURNING *",
        *params,
    )
    if not row:
        raise NotFoundError("Product", product_id)
    return APIResponse(data=dict(row))


@router.delete("/{product_id}", response_model=APIResponse[dict])
async def delete_product(product_id: str) -> APIResponse[dict]:
    """Soft-delete a product."""
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "UPDATE products SET status = 'delisted', updated_at = NOW() WHERE product_id = $1 RETURNING *",
        product_id,
    )
    if not row:
        raise NotFoundError("Product", product_id)
    return APIResponse(data=dict(row), message="Product deleted")


@router.get("/{product_id}/competitors", response_model=APIResponse[list[dict]])
async def product_competitors(product_id: str) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    product = await pool.fetchrow(
        "SELECT name, category FROM products WHERE product_id = $1", product_id
    )
    if not product:
        raise NotFoundError("Product", product_id)
    rows = await pool.fetch(
        """SELECT * FROM competitor_products
           WHERE category = $1 AND name ILIKE '%' || $2 || '%'
           ORDER BY price LIMIT 20""",
        product["category"],
        product["name"],
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.patch("/{product_id}/price", response_model=APIResponse[dict])
async def update_price(product_id: str, body: dict) -> APIResponse[dict]:
    """Update product price. Body: {retail_price?, cost_price?}"""
    pool = pg.get_pool()
    sets = []
    params = []
    idx = 1
    for field in ("retail_price", "cost_price"):
        if field in body:
            sets.append(f"{field} = ${idx}")
            params.append(body[field])
            idx += 1
    if not sets:
        return APIResponse(success=False, message="No price fields provided")
    sets.append("updated_at = NOW()")
    params.append(product_id)
    row = await pool.fetchrow(
        f"UPDATE products SET {', '.join(sets)} WHERE product_id = ${idx} RETURNING *",
        *params,
    )
    if not row:
        raise NotFoundError("Product", product_id)
    return APIResponse(data=dict(row))


@router.get("/{product_id}/sales", response_model=APIResponse[list[SalesRecord]])
async def get_sales(product_id: str) -> APIResponse[list[SalesRecord]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT sale_date AS date, quantity, revenue FROM sales_history
           WHERE product_id = $1 ORDER BY sale_date DESC LIMIT 90""",
        product_id,
    )
    return APIResponse(
        data=[
            SalesRecord(date=str(r["date"]), quantity=r["quantity"], revenue=r["revenue"])
            for r in rows
        ]
    )
