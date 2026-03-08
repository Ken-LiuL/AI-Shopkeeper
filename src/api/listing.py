"""Listing Agent API routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import (
    APIResponse,
    ListingCreateRequest,
    ListingDetail,
    ListingParseRequest,
    PaginatedResponse,
    TaskCreatedResponse,
)

router = APIRouter(prefix="/api/listing", tags=["listing"])
logger = logging.getLogger(__name__)


@router.get("/optimization", response_model=APIResponse[dict])
async def listing_optimization() -> APIResponse[dict]:
    """商品上架优化建议"""
    return APIResponse(data=None, message="商品上架优化功能开发中")


@router.get("", response_model=PaginatedResponse[dict])
async def list_listings(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> PaginatedResponse[dict]:
    """查询上架记录列表"""
    pool = pg.get_pool()
    try:
        # 构建查询
        where_clause = ""
        params: list = []
        if status:
            where_clause = "WHERE status = $1"
            params.append(status)

        # 总数
        count_sql = f"SELECT COUNT(*) FROM listings {where_clause}"
        total = await pool.fetchval(count_sql, *params)

        # 分页查询
        offset = (page - 1) * page_size
        if status:
            data_sql = "SELECT * FROM listings WHERE status = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3"
            rows = await pool.fetch(data_sql, status, page_size, offset)
        else:
            data_sql = "SELECT * FROM listings ORDER BY created_at DESC LIMIT $1 OFFSET $2"
            rows = await pool.fetch(data_sql, page_size, offset)

        return PaginatedResponse(
            data=[dict(r) for r in rows],
            total=total or 0,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.debug("listings 表查询失败（可能不存在）: %s", e)
        return PaginatedResponse(
            data=[],
            total=0,
            page=page,
            page_size=page_size,
            message="暂无上架记录",
        )


@router.put("/{listing_id}", response_model=APIResponse[dict])
async def update_listing(listing_id: str, body: dict) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        sets = []
        params = []
        idx = 1
        for k, v in body.items():
            if k in ("source_url", "platform", "product_data", "status"):
                sets.append(f"{k} = ${idx}")
                params.append(v if k != "product_data" else json.dumps(v))
                idx += 1
        if not sets:
            return APIResponse(success=False, message="No valid fields")
        params.append(listing_id)
        row = await pool.fetchrow(
            f"UPDATE listings SET {', '.join(sets)} WHERE listing_id = ${idx} RETURNING *",
            *params,
        )
        if not row:
            raise NotFoundError("Listing", listing_id)
        return APIResponse(data=dict(row))
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to update listing %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to update listing") from e


@router.post("/{listing_id}/publish", response_model=APIResponse[dict])
async def publish_listing(listing_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "UPDATE listings SET status = 'published', finished_at = NOW() WHERE listing_id = $1 RETURNING *",
            listing_id,
        )
        if not row:
            raise NotFoundError("Listing", listing_id)
        return APIResponse(data=dict(row), message="Listing published")
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to publish listing %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to publish listing") from e


@router.delete("/{listing_id}", response_model=APIResponse[dict])
async def delete_listing(listing_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "UPDATE listings SET status = 'deleted' WHERE listing_id = $1 AND status = 'processing' RETURNING *",
            listing_id,
        )
        if not row:
            raise NotFoundError("Listing", listing_id)
        return APIResponse(data=dict(row), message="Draft deleted")
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to delete listing %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to delete listing") from e


@router.post("/parse", response_model=APIResponse[dict])
async def parse_url(request: ListingParseRequest) -> APIResponse[dict]:
    """Quick parse of a product URL — returns extracted raw data."""
    try:
        from src.skills.actionbook import ActionBookSkill

        skill = ActionBookSkill()
        if request.platform == "alibaba":
            data = await skill.alibaba_detail(request.url)
        else:
            data = await skill.pdd_detail(request.url)
        return APIResponse(data=data.model_dump())
    except Exception as e:
        logger.error("Failed to parse URL %s: %s", request.url, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to parse URL: {e}") from e


async def _run_listing_create(
    listing_id: str, request: ListingCreateRequest, orch: Orchestrator
) -> None:
    try:
        result = await orch.run_listing(
            source_url=request.source_url,
            source_platform=request.platform,
            raw_product_data=request.raw_product_data,
        )
        pool = pg.get_pool()
        await pool.execute(
            """UPDATE listings SET status = 'completed', product_data = $1::jsonb, finished_at = NOW()
               WHERE listing_id = $2""",
            json.dumps(result, default=str),
            listing_id,
        )
    except Exception:
        logger.exception("Listing create %s failed", listing_id)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE listings SET status = 'failed', finished_at = NOW() WHERE listing_id = $1",
            listing_id,
        )


@router.post("/create", response_model=TaskCreatedResponse)
async def create_listing(
    request: ListingCreateRequest,
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> TaskCreatedResponse:
    listing_id = gen_id("lst_")
    pool = pg.get_pool()
    await pool.execute(
        "INSERT INTO listings (listing_id, status, source_url, platform, created_at) VALUES ($1, 'processing', $2, $3, NOW())",
        listing_id,
        request.source_url,
        request.platform,
    )
    bg.add_task(_run_listing_create, listing_id, request, orch)
    return TaskCreatedResponse(task_id=listing_id, message="Listing creation started")


@router.get("/{listing_id}", response_model=APIResponse[ListingDetail])
async def get_listing(listing_id: str) -> APIResponse[ListingDetail]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow("SELECT * FROM listings WHERE listing_id = $1", listing_id)
        if not row:
            raise NotFoundError("Listing", listing_id)
        data = dict(row)
        product_data = data.get("product_data") or {}
        if isinstance(product_data, str):
            product_data = json.loads(product_data)
        return APIResponse(
            data=ListingDetail(
                listing_id=data["listing_id"],
                status=data["status"],
                product_data=product_data,
                created_at=data.get("created_at"),
            )
        )
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to get listing %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to get listing") from e
