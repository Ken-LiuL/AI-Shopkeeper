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


@router.get("/{product_id}/sales", response_model=APIResponse[list[SalesRecord]])
async def get_sales(product_id: str) -> APIResponse[list[SalesRecord]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT sale_date AS date, quantity, revenue FROM sales_history
           WHERE product_id = $1 ORDER BY sale_date DESC LIMIT 90""",
        product_id,
    )
    return APIResponse(data=[SalesRecord(date=str(r["date"]), quantity=r["quantity"], revenue=r["revenue"]) for r in rows])
