"""Listing Agent API routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import APIResponse, ListingCreateRequest, ListingDetail, ListingParseRequest, TaskCreatedResponse

router = APIRouter(prefix="/api/listing", tags=["listing"])
logger = logging.getLogger(__name__)


@router.post("/parse", response_model=APIResponse[dict])
async def parse_url(request: ListingParseRequest) -> APIResponse[dict]:
    """Quick parse of a product URL — returns extracted raw data."""
    from src.skills.actionbook import parse_product_url  # type: ignore[import-untyped]

    data = await parse_product_url(request.url, request.platform)
    return APIResponse(data=data)


async def _run_listing_create(listing_id: str, request: ListingCreateRequest, orch: Orchestrator) -> None:
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
            json.dumps(result, default=str), listing_id,
        )
    except Exception:
        logger.exception("Listing create %s failed", listing_id)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE listings SET status = 'failed', finished_at = NOW() WHERE listing_id = $1", listing_id,
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
        listing_id, request.source_url, request.platform,
    )
    bg.add_task(_run_listing_create, listing_id, request, orch)
    return TaskCreatedResponse(task_id=listing_id, message="Listing creation started")


@router.get("/{listing_id}", response_model=APIResponse[ListingDetail])
async def get_listing(listing_id: str) -> APIResponse[ListingDetail]:
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
