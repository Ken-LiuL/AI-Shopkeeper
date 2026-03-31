"""Listing Agent API routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks

from src.db import postgres as pg

from .deps import gen_id
from .errors import NotFoundError
from .schemas import (
    APIResponse,
    BatchListingRequest,
    BatchListingResponse,
    ListingCreateRequest,
    ListingDetail,
    ListingParseRequest,
    ListingStatusResponse,
    PaginatedResponse,
    TaskCreatedResponse,
)

router = APIRouter(prefix="/api/listing", tags=["listing"])
logger = logging.getLogger(__name__)


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


@router.post("/parse", response_model=APIResponse[dict])
async def parse_url(request: ListingParseRequest) -> APIResponse[dict]:
    """Quick parse of a product URL — returns extracted raw data.

    Note: Direct URL parsing has been removed. Please use Chrome extension
    or manual import to add product data.
    """
    from fastapi import HTTPException
    raise HTTPException(
        status_code=501,
        detail="URL 解析功能已迁移至 Chrome 扩展，请使用手动导入或 Chrome 扩展添加商品数据",
    )


async def _update_listing_step(
    pool,
    listing_id: str,
    current_step: str,
    step_detail: str = "",
    **fields,
) -> None:
    """Helper: update listing progress in DB (non-blocking)."""
    try:
        set_parts = ["current_step = $1", "step_detail = $2"]
        params: list = [current_step, step_detail]
        idx = 3
        for col, val in fields.items():
            if val is not None:
                set_parts.append(f"{col} = ${idx}::jsonb")
                params.append(json.dumps(val, default=str))
                idx += 1
        params.append(listing_id)
        await pool.execute(
            f"UPDATE listings SET {', '.join(set_parts)} WHERE listing_id = ${idx}",
            *params,
        )
    except Exception as e:
        logger.warning("Failed to update listing step %s: %s", listing_id, e)


async def _run_listing_create(
    listing_id: str, request: ListingCreateRequest
) -> None:
    """Background task: run listing pipeline with per-step DB progress updates."""
    from src.agents.listing.nodes import (
        compliance_node,
        filler_node,
        matcher_node,
        parser_node,
    )

    pool = pg.get_pool()

    # Build initial state
    state = {
        "source_url": request.source_url,
        "source_platform": request.platform,
        "raw_product_data": request.raw_product_data,
        "errors": [],
    }

    try:
        # ── Step 1: Parser ────────────────────────────────────────────────
        await _update_listing_step(pool, listing_id, "parsing", "正在解析商品信息...")
        parser_result = await parser_node(state)
        state.update(parser_result)

        if "errors" in parser_result and parser_result["errors"]:
            await pool.execute(
                """UPDATE listings SET status = 'failed', current_step = 'parsing',
                   errors = $1::jsonb, finished_at = NOW() WHERE listing_id = $2""",
                json.dumps(state.get("errors", []), default=str),
                listing_id,
            )
            return

        await pool.execute(
            """UPDATE listings SET parsed_product = $1::jsonb, current_step = 'matching',
               step_detail = '正在匹配美团标品库...' WHERE listing_id = $2""",
            json.dumps(parser_result.get("parsed_product"), default=str),
            listing_id,
        )

        # ── Step 2: Matcher ───────────────────────────────────────────────
        matcher_result = await matcher_node(state)
        state.update(matcher_result)

        if "errors" in matcher_result and matcher_result.get("errors"):
            # Matcher failure is non-fatal — continue with empty match
            logger.warning("Matcher failed for %s, continuing: %s", listing_id, matcher_result["errors"])

        await pool.execute(
            """UPDATE listings SET
               matched_standard = $1::jsonb,
               match_confidence = $2,
               current_step = 'filling',
               step_detail = '正在填充上架信息...'
               WHERE listing_id = $3""",
            json.dumps(matcher_result.get("matched_standard"), default=str),
            matcher_result.get("match_confidence"),
            listing_id,
        )

        # ── Step 3: Filler ────────────────────────────────────────────────
        filler_result = await filler_node(state)
        state.update(filler_result)

        if "errors" in filler_result and filler_result.get("errors"):
            await pool.execute(
                """UPDATE listings SET status = 'failed', current_step = 'filling',
                   errors = $1::jsonb, finished_at = NOW() WHERE listing_id = $2""",
                json.dumps(state.get("errors", []), default=str),
                listing_id,
            )
            return

        await pool.execute(
            """UPDATE listings SET
               listing_info = $1::jsonb,
               current_step = 'compliance',
               step_detail = '正在进行合规校验...'
               WHERE listing_id = $2""",
            json.dumps(filler_result.get("listing_info"), default=str),
            listing_id,
        )

        # ── Step 4: Compliance ────────────────────────────────────────────
        compliance_result = await compliance_node(state)
        state.update(compliance_result)

        if "errors" in compliance_result and compliance_result.get("errors"):
            logger.warning("Compliance check failed for %s, continuing: %s", listing_id, compliance_result["errors"])

        # ── Final: Mark completed ─────────────────────────────────────────
        errors_json = json.dumps(state.get("errors") or [], default=str)
        await pool.execute(
            """UPDATE listings SET
               status = 'completed',
               compliance_check = $1::jsonb,
               current_step = 'done',
               step_detail = '上架完成',
               errors = $2::jsonb,
               finished_at = NOW()
               WHERE listing_id = $3""",
            json.dumps(compliance_result.get("compliance_check"), default=str),
            errors_json,
            listing_id,
        )

    except Exception:
        logger.exception("Listing create %s failed", listing_id)
        try:
            await pool.execute(
                """UPDATE listings SET status = 'failed', current_step = 'failed',
                   step_detail = '处理失败，请重试', finished_at = NOW() WHERE listing_id = $1""",
                listing_id,
            )
        except Exception as inner:
            logger.error("Failed to mark listing %s as failed: %s", listing_id, inner)


@router.post("/create", response_model=TaskCreatedResponse)
async def create_listing(
    request: ListingCreateRequest,
    bg: BackgroundTasks,
) -> TaskCreatedResponse:
    listing_id = gen_id("lst_")
    pool = pg.get_pool()
    await pool.execute(
        """INSERT INTO listings
           (listing_id, status, source_url, platform, raw_product_data, current_step, step_detail, created_at)
           VALUES ($1, 'processing', $2, $3, $4, 'parsing', '任务已创建，等待处理...', NOW())""",
        listing_id,
        request.source_url,
        request.platform,
        request.raw_product_data,
    )
    bg.add_task(_run_listing_create, listing_id, request)
    return TaskCreatedResponse(task_id=listing_id, message="Listing creation started")


@router.post("/batch", response_model=BatchListingResponse)
async def batch_create_listing(
    request: BatchListingRequest,
    bg: BackgroundTasks,
) -> BatchListingResponse:
    """批量上架：为每个商品创建独立的 listing task。"""
    if not request.items:
        return BatchListingResponse(success=False, message="items 不能为空")

    pool = pg.get_pool()
    task_ids: list[str] = []

    for item in request.items:
        listing_id = gen_id("lst_")
        try:
            await pool.execute(
                """INSERT INTO listings
                   (listing_id, status, source_url, platform, raw_product_data, current_step, step_detail, created_at)
                   VALUES ($1, 'processing', $2, $3, $4, 'parsing', '任务已创建，等待处理...', NOW())""",
                listing_id,
                item.source_url,
                item.platform,
                item.raw_product_data,
            )
            listing_req = ListingCreateRequest(
                source_url=item.source_url,
                platform=item.platform,
                raw_product_data=item.raw_product_data,
            )
            bg.add_task(_run_listing_create, listing_id, listing_req)
            task_ids.append(listing_id)
        except Exception as e:
            logger.error("Failed to create batch listing item: %s", e)
            # Continue with remaining items

    return BatchListingResponse(
        task_ids=task_ids,
        message=f"已创建 {len(task_ids)}/{len(request.items)} 个上架任务",
    )


@router.get("/{listing_id}/status", response_model=APIResponse[ListingStatusResponse])
async def get_listing_status(listing_id: str) -> APIResponse[ListingStatusResponse]:
    """轻量级进度查询端点，供前端轮询使用。"""
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "SELECT listing_id, status, current_step, step_detail, created_at FROM listings WHERE listing_id = $1",
            listing_id,
        )
        if not row:
            raise NotFoundError("Listing", listing_id)
        data = dict(row)
        return APIResponse(
            data=ListingStatusResponse(
                listing_id=data["listing_id"],
                status=data["status"],
                current_step=data.get("current_step"),
                step_detail=data.get("step_detail"),
                created_at=data.get("created_at"),
            )
        )
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to get listing status %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to get listing status") from e


@router.get("/{listing_id}", response_model=APIResponse[ListingDetail])
async def get_listing(listing_id: str) -> APIResponse[ListingDetail]:
    """获取上架任务完整详情（含各步骤结果）。"""
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow("SELECT * FROM listings WHERE listing_id = $1", listing_id)
        if not row:
            raise NotFoundError("Listing", listing_id)
        data = dict(row)

        def _parse_jsonb(val):
            if val is None:
                return None
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return None
            return val  # asyncpg already decoded JSONB to dict/list

        errors_raw = _parse_jsonb(data.get("errors"))
        if errors_raw is not None and not isinstance(errors_raw, list):
            errors_raw = [errors_raw]

        return APIResponse(
            data=ListingDetail(
                listing_id=data["listing_id"],
                status=data["status"],
                current_step=data.get("current_step"),
                step_detail=data.get("step_detail"),
                parsed_product=_parse_jsonb(data.get("parsed_product")),
                matched_standard=_parse_jsonb(data.get("matched_standard")),
                match_confidence=data.get("match_confidence"),
                listing_info=_parse_jsonb(data.get("listing_info")),
                compliance_check=_parse_jsonb(data.get("compliance_check")),
                errors=errors_raw,
                created_at=data.get("created_at"),
                finished_at=data.get("finished_at"),
            )
        )
    except NotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to get listing %s: %s", listing_id, e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to get listing") from e
