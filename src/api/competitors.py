"""Competitor analysis API routes."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .schemas import APIResponse, PaginatedResponse

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


@router.get("/stores", response_model=PaginatedResponse[dict])
async def list_stores(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        total = await pool.fetchval("SELECT COUNT(*) FROM competitor_stores") or 0
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            "SELECT * FROM competitor_stores ORDER BY last_synced DESC LIMIT $1 OFFSET $2",
            page_size,
            offset,
        )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/stores/{store_id}/products", response_model=PaginatedResponse[dict])
async def store_products(
    store_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        total = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM competitor_products WHERE store_id = $1",
                store_id,
            )
            or 0
        )
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            "SELECT * FROM competitor_products WHERE store_id = $1 ORDER BY last_synced DESC LIMIT $2 OFFSET $3",
            store_id,
            page_size,
            offset,
        )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/products", response_model=PaginatedResponse[dict])
async def search_competitor_products(
    q: str | None = Query(None),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        conditions: list[str] = []
        params: list = []
        idx = 1
        if q:
            conditions.append(f"name ILIKE ${idx}")
            params.append(f"%{q}%")
            idx += 1
        if category:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        total = (
            await pool.fetchval(f"SELECT COUNT(*) FROM competitor_products{where}", *params) or 0
        )
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            f"SELECT * FROM competitor_products{where} ORDER BY last_synced DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            page_size,
            offset,
        )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/keywords", response_model=APIResponse[list[dict]])
async def hot_keywords(
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT keyword, search_volume, result_count, avg_price, last_synced
               FROM competitor_keywords ORDER BY search_volume DESC LIMIT $1""",
            limit,
        )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/price-comparison", response_model=APIResponse[list[dict]])
async def price_comparison(
    product_id: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = []
    with contextlib.suppress(Exception):
        conditions: list[str] = []
        params: list = []
        idx = 1
        if product_id:
            conditions.append(f"p.spu_id = ${idx}")
            params.append(product_id)
            idx += 1
        if category:
            conditions.append(f"p.category = ${idx}")
            params.append(category)
            idx += 1
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await pool.fetch(
            f"""SELECT p.spu_id AS product_id, p.name, p.retail_price AS our_price,
                       cp.name AS competitor_name, cp.price AS competitor_price,
                       cs.name AS competitor_store,
                       ROUND((p.retail_price - cp.price) / NULLIF(cp.price, 0) * 100, 2) AS price_diff_pct
                FROM qnh_products p
                JOIN competitor_products cp ON cp.category = p.category
                LEFT JOIN competitor_stores cs ON cp.store_id = cs.store_id
                {where}
                ORDER BY price_diff_pct DESC LIMIT ${idx}""",
            *params,
        )
    return APIResponse(data=[dict(r) for r in rows])
