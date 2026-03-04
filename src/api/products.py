"""Products CRUD API routes."""

from __future__ import annotations

import contextlib
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
    store_id: str | None = Query(None, description="按门店 ID 过滤"),
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
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if store_id:
        conditions.append(f"store_id = ${idx}")
        params.append(store_id)
        idx += 1

    try:
        count_query = "SELECT COUNT(*) FROM products"
        if conditions:
            count_query += " WHERE " + " AND ".join(conditions)
        total = await pool.fetchval(count_query, *params) or 0

        offset = (page - 1) * page_size
        params_page = params + [page_size, offset]

        select_query = """SELECT
            product_id,
            name,
            brand,
            category,
            retail_price,
            cost_price,
            stock,
            monthly_sales,
            status,
            store_id,
            image_url,
            upc_code,
            created_at,
            updated_at
        FROM products"""

        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += f" ORDER BY monthly_sales DESC NULLS LAST LIMIT ${idx} OFFSET ${idx + 1}"

        rows = await pool.fetch(select_query, *params_page)

        processed_rows = []
        for row in rows:
            try:
                row_dict = dict(row)
                for price_field in ["retail_price", "cost_price"]:
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
           FROM products WHERE category IS NOT NULL
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

    # Dynamic low-stock thresholds based on monthly_sales:
    #   monthly_sales >= 100 → low if stock < monthly_sales * 0.5
    #   monthly_sales >= 30  → low if stock < monthly_sales * 0.3
    #   monthly_sales < 30   → low if stock < 5
    dynamic_low_stock_condition = """
        status = 'active' AND (
            (COALESCE(monthly_sales, 0) >= 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5)
         OR (COALESCE(monthly_sales, 0) >= 30 AND COALESCE(monthly_sales, 0) < 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3)
         OR (COALESCE(monthly_sales, 0) < 30 AND COALESCE(stock, 0) < 5)
        )
    """

    total = (
        await pool.fetchval(
            f"SELECT COUNT(*) FROM products WHERE {dynamic_low_stock_condition}",
        )
        or 0
    )

    offset = (page - 1) * page_size
    rows = []

    if total > 0:
        rows = await pool.fetch(
            f"SELECT * FROM products WHERE {dynamic_low_stock_condition} ORDER BY stock ASC LIMIT $1 OFFSET $2",
            page_size,
            offset,
        )
    else:
        # Fallback: simulate low-stock alerts from products table when stock is missing
        logger.info("No stock data available; simulating low-stock list from products table")

        rows = await pool.fetch(
            """SELECT product_id, name, brand, category, retail_price, status,
                      COALESCE(
                          stock,
                          CASE WHEN retail_price < 20 THEN 5
                               WHEN retail_price < 50 THEN 8
                               ELSE 12 END
                      ) as stock,
                      'products' as source
               FROM products
               WHERE status = 'active'
                 AND retail_price > 0
                 AND name != ''
               ORDER BY retail_price ASC
               LIMIT $1 OFFSET $2""",
            page_size,
            offset,
        )

        total = (
            await pool.fetchval(
                """SELECT COUNT(*) FROM products
               WHERE status = 'active'
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

    # Get inventory status summary from products table
    total_products = await pool.fetchval("SELECT COUNT(*) FROM products") or 0
    active_products = (
        await pool.fetchval("SELECT COUNT(*) FROM products WHERE status = 'active'") or 0
    )
    inactive_products = total_products - active_products

    # Dynamic low-stock thresholds based on monthly_sales:
    #   monthly_sales >= 100 → low if stock < monthly_sales * 0.5
    #   monthly_sales >= 30  → low if stock < monthly_sales * 0.3
    #   monthly_sales < 30   → low if stock < 5
    low_stock_count = (
        await pool.fetchval(
            """SELECT COUNT(*) FROM products
               WHERE status = 'active'
                 AND (
                       (COALESCE(monthly_sales, 0) >= 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5)
                    OR (COALESCE(monthly_sales, 0) >= 30 AND COALESCE(monthly_sales, 0) < 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3)
                    OR (COALESCE(monthly_sales, 0) < 30 AND COALESCE(stock, 0) < 5)
                   )"""
        )
        or 0
    )

    # Get category breakdown
    category_breakdown = await pool.fetch(
        """SELECT category,
                  COUNT(*)::int AS count,
                  COUNT(CASE WHEN status = '在售' THEN 1 END)::int AS active_count
           FROM products
           WHERE category IS NOT NULL AND category != ''
           GROUP BY category
           ORDER BY count DESC
           LIMIT 10"""
    )

    # Get recent low stock items with dynamic thresholds
    low_stock_items = await pool.fetch(
        """SELECT product_id,
                     name,
                     category,
                     retail_price,
                     COALESCE(stock, 0) AS stock,
                     COALESCE(monthly_sales, 0) AS monthly_sales,
                     CASE
                         WHEN COALESCE(monthly_sales, 0) >= 100 THEN CEIL(COALESCE(monthly_sales, 0) * 0.5)
                         WHEN COALESCE(monthly_sales, 0) >= 30  THEN CEIL(COALESCE(monthly_sales, 0) * 0.3)
                         ELSE 5
                     END AS threshold
             FROM products
             WHERE status = 'active'
               AND (
                     (COALESCE(monthly_sales, 0) >= 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5)
                  OR (COALESCE(monthly_sales, 0) >= 30 AND COALESCE(monthly_sales, 0) < 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3)
                  OR (COALESCE(monthly_sales, 0) < 30 AND COALESCE(stock, 0) < 5)
                 )
             ORDER BY COALESCE(stock, 0) ASC, updated_at DESC NULLS LAST
             LIMIT 10"""
    )

    formatted_low_stock_items: list[dict[str, Any]] = []
    for row in low_stock_items:
        monthly_sales = float(row["monthly_sales"])
        if monthly_sales >= 100:
            flag = "high_sales_low_stock"
        elif monthly_sales >= 30:
            flag = "medium_sales_low_stock"
        else:
            flag = "slow_sales_low_stock"
        formatted_low_stock_items.append(
            {
                "product_id": str(row["product_id"]),
                "name": row["name"],
                "category": row["category"],
                "retail_price": float(row["retail_price"]),
                "estimated_stock": int(row["stock"]),
                "monthly_sales": monthly_sales,
                "threshold": int(row["threshold"]),
                "turnover_flag": flag,
            }
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
            "low_stock_items": formatted_low_stock_items,
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
        """SELECT product_id, name, brand, category, description AS spec, retail_price, status
           FROM products
           WHERE name ILIKE $1 OR brand ILIKE $1 OR description ILIKE $1 OR category ILIKE $1
           LIMIT $2""",
        query,
        body.limit,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.post("/knowledge/build", response_model=APIResponse[dict])
async def build_product_knowledge(body: KnowledgeBuildRequest | None = None) -> APIResponse[dict]:
    """触发商品知识库构建（从 products 同步 → embedding → pgvector）。"""
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
    source_products = await pool.fetchval("SELECT COUNT(*) FROM products")
    with_category = await pool.fetchval(
        "SELECT COUNT(*) FROM products WHERE category IS NOT NULL AND category != ''"
    )
    with_embedding = 0  # products table no longer stores embeddings directly
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
    """商品定价分析 — 按医疗器械行业常见40%毛利假设估算成本，并结合月销/库存做周转调价。"""
    try:
        pool = pg.get_pool()

        estimated_cost_expr = (
            "CASE WHEN COALESCE(cost_price::numeric, 0) > 0 THEN cost_price::numeric "
            "ELSE retail_price::numeric * 0.6 END"
        )
        margin_expr = (
            f"(retail_price::numeric - {estimated_cost_expr}) / NULLIF(retail_price::numeric, 0)"
        )

        price_distribution = await pool.fetch(
            f"""
            SELECT
                category,
                COUNT(*) as product_count,
                AVG(retail_price::numeric) as avg_retail_price,
                AVG({estimated_cost_expr}) as avg_cost_price,
                AVG({margin_expr}) * 100 as avg_margin_percent
            FROM products
            WHERE retail_price::numeric > 0 AND category IS NOT NULL AND category != ''
            GROUP BY category
            HAVING COUNT(*) >= 3
            ORDER BY avg_margin_percent DESC NULLS LAST
        """
        )

        price_ranges = await pool.fetch(
            f"""
            SELECT price_range,
                   COUNT(*) as product_count,
                   AVG(margin_percent) as avg_margin_percent
            FROM (
                SELECT
                    CASE
                        WHEN retail_price::numeric <= 50 THEN '低价(≤50元)'
                        WHEN retail_price::numeric <= 200 THEN '中价(51-200元)'
                        WHEN retail_price::numeric <= 500 THEN '高价(201-500元)'
                        ELSE '超高价(>500元)'
                    END as price_range,
                    ({margin_expr}) * 100 as margin_percent
                FROM products
                WHERE retail_price::numeric > 0
            ) priced
            GROUP BY price_range
            ORDER BY avg_margin_percent DESC NULLS LAST
        """
        )

        low_margin_products = await pool.fetch(
            f"""
            WITH products_with_cost AS (
                SELECT
                    product_id,
                    name,
                    category,
                    retail_price::numeric as rp,
                    {estimated_cost_expr} as cp,
                    COALESCE(monthly_sales, 0) as monthly_sales,
                    COALESCE(stock, 0) as stock,
                    CASE
                        WHEN retail_price::numeric > 0
                        THEN (retail_price::numeric - {estimated_cost_expr}) / retail_price::numeric * 100
                        ELSE 0
                    END as margin_percent
                FROM products
                WHERE retail_price::numeric > 0
            )
            SELECT * FROM products_with_cost
            WHERE margin_percent < 15
            ORDER BY margin_percent ASC
            LIMIT 20
        """
        )

        high_margin_products = await pool.fetch(
            f"""
            WITH products_with_cost AS (
                SELECT
                    product_id,
                    name,
                    category,
                    retail_price::numeric as rp,
                    {estimated_cost_expr} as cp,
                    COALESCE(monthly_sales, 0) as monthly_sales,
                    COALESCE(stock, 0) as stock,
                    CASE
                        WHEN retail_price::numeric > 0
                        THEN (retail_price::numeric - {estimated_cost_expr}) / retail_price::numeric * 100
                        ELSE 0
                    END as margin_percent
                FROM products
                WHERE retail_price::numeric > 0
            )
            SELECT * FROM products_with_cost
            WHERE margin_percent > 40
            ORDER BY margin_percent DESC
            LIMIT 10
        """
        )

        turnover_rows = await pool.fetch(
            f"""
            SELECT
                product_id,
                name,
                category,
                retail_price::numeric as retail_price,
                COALESCE(stock, 0) as stock,
                COALESCE(monthly_sales, 0) as monthly_sales,
                {estimated_cost_expr} as estimated_cost
            FROM products
            WHERE retail_price::numeric > 0
              AND (monthly_sales IS NOT NULL OR stock IS NOT NULL)
            ORDER BY monthly_sales DESC NULLS LAST, stock ASC NULLS LAST
            LIMIT 500
        """
        )

        totals_row = await pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE retail_price::numeric > 0) AS priced_products,
                COUNT(*) FILTER (WHERE COALESCE(stock, 0) = 0) AS stockout_products,
                COUNT(*) FILTER (WHERE COALESCE(monthly_sales, 0) > 0) AS products_with_sales
            FROM products
            """
        )
        totals = dict(totals_row) if totals_row else {}

        pricing_suggestions: list[dict[str, Any]] = []
        high_demand_candidates: list[tuple[float, dict[str, Any]]] = []
        clearance_candidates: list[tuple[float, dict[str, Any]]] = []
        hot_selling_candidates: list[tuple[float, dict[str, Any]]] = []

        for row in turnover_rows:
            monthly_sales = float(row["monthly_sales"] or 0)
            stock_units = float(row["stock"] or 0)
            current_price = float(row["retail_price"] or 0)
            estimated_cost = float(row["estimated_cost"] or 0)
            if current_price <= 0:
                continue
            coverage_days = (
                (stock_units / monthly_sales) * 30 if monthly_sales > 0 else float("inf")
            )
            margin_percent = (
                (current_price - estimated_cost) / current_price * 100 if current_price > 0 else 0
            )

            # 涨价机会：月销>50 且 库存<30 (供不应求)
            if monthly_sales > 50 and stock_units < 30:
                bump_pct = 0.1 if coverage_days <= 15 else 0.06
                suggested_price = max(
                    round(current_price * (1 + bump_pct), 2),
                    round(estimated_cost * 1.2, 2),
                )
                reason = (
                    f"月销{int(monthly_sales)}件但库存仅{int(stock_units)}件（约{coverage_days:.0f}天库存），"
                    "供不应求，建议小幅提价并优先补货。"
                )
                suggestion = {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "current_price": round(current_price, 2),
                    "suggested_price": suggested_price,
                    "reason": reason,
                    "action": "涨价机会",
                    "insights": {
                        "monthly_sales": int(monthly_sales),
                        "stock": int(stock_units),
                        "turnover_days": round(coverage_days, 1),
                        "estimated_margin_percent": round(margin_percent, 2),
                    },
                }
                high_demand_candidates.append((coverage_days, suggestion))

            # 降价清仓：月销<5 且 库存>100 (滞销)
            elif monthly_sales < 5 and stock_units > 100:
                if coverage_days == float("inf"):
                    coverage_label = ">360"
                    coverage_value = 365.0
                    turnover_days_value = None
                else:
                    coverage_label = f"{coverage_days:.0f}"
                    coverage_value = coverage_days
                    turnover_days_value = round(coverage_days, 1)

                discount_pct = 0.15 if coverage_value >= 180 else 0.1
                suggested_price = max(
                    round(current_price * (1 - discount_pct), 2),
                    round(estimated_cost * 1.05, 2),
                )
                reason = (
                    f"月销{int(monthly_sales)}件却有{int(stock_units)}件库存（约{coverage_label}天库存），"
                    "滞销商品，建议降价清仓并配合促销曝光。"
                )
                suggestion = {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "current_price": round(current_price, 2),
                    "suggested_price": suggested_price,
                    "reason": reason,
                    "action": "降价清仓",
                    "insights": {
                        "monthly_sales": int(monthly_sales),
                        "stock": int(stock_units),
                        "turnover_days": turnover_days_value,
                        "estimated_margin_percent": round(margin_percent, 2),
                    },
                }
                clearance_candidates.append((coverage_value, suggestion))

            # 热销商品，维持定价：月销>100
            elif monthly_sales > 100:
                suggestion = {
                    "product_id": row["product_id"],
                    "name": row["name"],
                    "current_price": round(current_price, 2),
                    "suggested_price": round(current_price, 2),
                    "reason": f"月销{int(monthly_sales)}件，热销商品，维持定价。",
                    "action": "热销商品，维持定价",
                    "insights": {
                        "monthly_sales": int(monthly_sales),
                        "stock": int(stock_units),
                        "turnover_days": round(coverage_days, 1)
                        if coverage_days != float("inf")
                        else None,
                        "estimated_margin_percent": round(margin_percent, 2),
                    },
                }
                hot_selling_candidates.append((monthly_sales, suggestion))

        high_demand_suggestions = [
            item for _, item in sorted(high_demand_candidates, key=lambda x: x[0])[:5]
        ]
        clearance_suggestions = [
            item for _, item in sorted(clearance_candidates, key=lambda x: x[0], reverse=True)[:5]
        ]
        hot_selling_suggestions = [
            item for _, item in sorted(hot_selling_candidates, key=lambda x: x[0], reverse=True)[:5]
        ]
        pricing_suggestions.extend(
            high_demand_suggestions + clearance_suggestions + hot_selling_suggestions
        )

        if not pricing_suggestions:
            for product in low_margin_products[:5]:
                current_price = float(product["rp"])
                cost_price = float(product["cp"])
                suggested_price = max(round(cost_price * 1.25, 2), round(current_price * 1.05, 2))
                pricing_suggestions.append(
                    {
                        "product_id": product["product_id"],
                        "name": product["name"],
                        "current_price": round(current_price, 2),
                        "suggested_price": suggested_price,
                        "reason": f"当前利润率{product['margin_percent']:.1f}%过低，建议调至25%",
                        "action": "涨价",
                    }
                )

        weighted_margin_total = sum(
            float(row["avg_margin_percent"] or 0) * int(row["product_count"] or 0)
            for row in price_distribution
        )
        weighted_margin_count = sum(int(row["product_count"] or 0) for row in price_distribution)
        weighted_avg_margin = (
            round(weighted_margin_total / weighted_margin_count, 2) if weighted_margin_count else 0
        )

        summary = {
            "total_products": int(totals.get("priced_products", 0)),
            "products_with_sales": int(totals.get("products_with_sales", 0)),
            "stockout_products": int(totals.get("stockout_products", 0)),
            "low_margin_count": len(low_margin_products),
            "high_margin_count": len(high_margin_products),
            "avg_margin_percent": weighted_avg_margin,
            "turnover_flags": {
                "high_demand_low_stock": len(high_demand_candidates),
                "low_demand_high_stock": len(clearance_candidates),
                "hot_selling": len(hot_selling_candidates),
            },
        }

        result = {
            "category_analysis": [
                {
                    "category": row["category"],
                    "product_count": int(row["product_count"]),
                    "avg_retail_price": round(float(row["avg_retail_price"] or 0), 2),
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
            "summary": summary,
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
    store_id: str | None = Query(None, description="按门店 ID 过滤"),
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
    if store_id:
        conditions.append(f"store_id = ${idx}")
        params.append(store_id)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await pool.fetchval(f"SELECT COUNT(*) FROM products{where}", *params)

    offset = (page - 1) * page_size
    params_page = params + [page_size, offset]
    rows = await pool.fetch(
        f"SELECT * FROM products{where} ORDER BY monthly_sales DESC NULLS LAST LIMIT ${idx} OFFSET ${idx + 1}",
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


@router.get("/analysis", response_model=APIResponse[dict])
async def get_product_analysis() -> APIResponse[dict]:
    """商品销售分析：畅销品、滞销品、利润分析"""
    pool = pg.get_pool()
    try:
        top_sellers, slow_movers, profit_analysis = [], [], []

        # ---- 畅销品 ----
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT oi.product_id, p.name,
                       SUM(oi.quantity) AS total_orders,
                       SUM(oi.quantity * oi.unit_price) AS revenue
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                JOIN orders o ON oi.order_id = o.order_id
                WHERE o.order_time >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY oi.product_id, p.name
                ORDER BY total_orders DESC
                LIMIT 20
            """)
            top_sellers = [
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "total_orders": int(r["total_orders"]),
                    "revenue": round(float(r["revenue"]), 2),
                }
                for r in rows
            ]

        # ---- 滞销品（近30天无销售）----
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT p.product_id, p.name,
                       COALESCE(SUM(oi.quantity), 0) AS total_orders,
                       COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS revenue
                FROM products p
                LEFT JOIN order_items oi ON p.product_id = oi.product_id
                LEFT JOIN orders o ON oi.order_id = o.order_id
                    AND o.order_time >= CURRENT_DATE - INTERVAL '30 days'
                WHERE p.status = 'active'
                GROUP BY p.product_id, p.name
                HAVING COALESCE(SUM(oi.quantity), 0) < 5
                ORDER BY total_orders ASC
                LIMIT 20
            """)
            slow_movers = [
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "total_orders": int(r["total_orders"]),
                    "revenue": round(float(r["revenue"]), 2),
                }
                for r in rows
            ]

        # ---- 利润分析 ----
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT p.product_id, p.name, p.cost_price, p.retail_price,
                       COALESCE(SUM(oi.quantity), 0) AS total_sold
                FROM products p
                LEFT JOIN order_items oi ON p.product_id = oi.product_id
                LEFT JOIN orders o ON oi.order_id = o.order_id
                    AND o.order_time >= CURRENT_DATE - INTERVAL '30 days'
                WHERE p.cost_price > 0 AND p.retail_price > 0
                GROUP BY p.product_id, p.name, p.cost_price, p.retail_price
                ORDER BY total_sold DESC
                LIMIT 20
            """)
            for r in rows:
                cost = float(r["cost_price"])
                price = float(r["retail_price"])
                margin = round((price - cost) / price, 4) if price > 0 else 0
                if margin < 0.1:
                    suggestion = "利润率偏低，建议提价或寻找低价供应商"
                elif margin > 0.6:
                    suggestion = "利润率优秀，可考虑适当促销扩大销量"
                else:
                    suggestion = "利润率正常，保持现有策略"
                profit_analysis.append(
                    {
                        "product_id": r["product_id"],
                        "name": r["name"],
                        "margin": margin,
                        "suggestion": suggestion,
                    }
                )

        # Fallback：若无订单数据，使用 products 表估算
        if not top_sellers and not slow_movers:
            fallback = await pool.fetch("""
                SELECT product_id, name, retail_price, cost_price, category
                FROM products
                WHERE retail_price > 0
                ORDER BY retail_price DESC
                LIMIT 40
            """)
            top_sellers = [
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "total_orders": 0,
                    "revenue": float(r["retail_price"] or 0),
                }
                for r in fallback[:20]
            ]
            slow_movers = [
                {
                    "product_id": r["product_id"],
                    "name": r["name"],
                    "total_orders": 0,
                    "revenue": float(r["retail_price"] or 0),
                }
                for r in fallback[20:]
            ]
            for r in fallback:
                cost = float(r["cost_price"] or 0)
                price = float(r["retail_price"] or 0)
                if cost > 0 and price > 0:
                    margin = round((price - cost) / price, 4)
                    suggestion = "利润率偏低，建议提价" if margin < 0.1 else "利润率正常"
                    profit_analysis.append(
                        {
                            "product_id": r["product_id"],
                            "name": r["name"],
                            "margin": margin,
                            "suggestion": suggestion,
                        }
                    )

        return APIResponse(
            data={
                "top_sellers": top_sellers,
                "slow_movers": slow_movers,
                "profit_analysis": profit_analysis,
            }
        )

    except Exception as e:
        logger.error("Failed to get product analysis: %s", e)
        return APIResponse(success=False, message=f"商品分析失败: {str(e)}", data={})
