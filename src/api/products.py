"""Products CRUD API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

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

router = APIRouter(prefix="/api/products", tags=["products"])


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

    total = await pool.fetchval(f"SELECT COUNT(*) FROM products{where}", *params)

    offset = (page - 1) * page_size
    params_page = params + [page_size, offset]
    rows = await pool.fetch(
        f"SELECT * FROM products{where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params_page,
    )
    return PaginatedResponse(data=[dict(r) for r in rows], total=total, page=page, page_size=page_size)


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
        product_id, body.name, body.barcode, body.category, body.brand,
        body.description, body.cost_price, body.retail_price, body.stock, body.status,
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
        "UPDATE products SET status = 'deleted', updated_at = NOW() WHERE product_id = $1 RETURNING *",
        product_id,
    )
    if not row:
        raise NotFoundError("Product", product_id)
    return APIResponse(data=dict(row), message="Product deleted")


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
                pid, item.name, item.barcode, item.category, item.brand,
                item.description, item.cost_price, item.retail_price, item.stock, item.status,
            )
            created += 1
        except Exception as e:
            errors.append({"index": i, "error": str(e)})
    return APIResponse(data={"created": created, "errors": errors})


@router.get("/export")
async def export_products(
    status: str | None = Query(None),
) -> "StreamingResponse":
    """Export products as CSV."""
    import csv, io
    from fastapi.responses import StreamingResponse

    pool = pg.get_pool()
    if status:
        rows = await pool.fetch("SELECT * FROM products WHERE status = $1 ORDER BY created_at DESC", status)
    else:
        rows = await pool.fetch("SELECT * FROM products ORDER BY created_at DESC")

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(dict(rows[0]).keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: str(v) for k, v in dict(r).items()})
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=products.csv"})


@router.get("/categories", response_model=APIResponse[list[dict]])
async def list_categories() -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT category, COUNT(*)::int AS product_count
           FROM products WHERE status != 'deleted' AND category IS NOT NULL
           GROUP BY category ORDER BY product_count DESC"""
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/{product_id}/competitors", response_model=APIResponse[list[dict]])
async def product_competitors(product_id: str) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    product = await pool.fetchrow("SELECT name, category FROM products WHERE product_id = $1", product_id)
    if not product:
        raise NotFoundError("Product", product_id)
    rows = await pool.fetch(
        """SELECT * FROM competitor_products
           WHERE category = $1 AND name ILIKE '%' || $2 || '%'
           ORDER BY price LIMIT 20""",
        product["category"], product["name"],
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


@router.get("/low-stock", response_model=PaginatedResponse[dict])
async def low_stock(
    threshold: int = Query(10, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = await pool.fetchval(
        "SELECT COUNT(*) FROM products WHERE stock <= $1 AND status = 'active'", threshold,
    )
    offset = (page - 1) * page_size
    rows = await pool.fetch(
        "SELECT * FROM products WHERE stock <= $1 AND status = 'active' ORDER BY stock ASC LIMIT $2 OFFSET $3",
        threshold, page_size, offset,
    )
    return PaginatedResponse(data=[dict(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/{product_id}/sales", response_model=APIResponse[list[SalesRecord]])
async def get_sales(product_id: str) -> APIResponse[list[SalesRecord]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT sale_date AS date, quantity, revenue FROM sales_history
           WHERE product_id = $1 ORDER BY sale_date DESC LIMIT 90""",
        product_id,
    )
    return APIResponse(data=[SalesRecord(date=str(r["date"]), quantity=r["quantity"], revenue=r["revenue"]) for r in rows])
