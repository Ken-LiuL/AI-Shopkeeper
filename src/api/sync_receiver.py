"""数据同步接收 API — 接收本地 daemon 推送的 QNH 数据。

架构: 本地 daemon (nodriver) → POST /api/sync/ingest → Render 后端 → DB
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .deps import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])

SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")

# source → DB 表映射
SOURCE_TABLE_MAP = {
    "metrics": "qnh_store_metrics",
    "products": "qnh_products",
    "orders": "qnh_orders",
    "inventory": "qnh_inventory",
    "reviews": "qnh_reviews",
    "traffic": "qnh_traffic",
    "promotions": "qnh_promotions",
    "customers": "qnh_customers",
    "refunds": "qnh_refunds",
    "finance": "qnh_settlements",
    "im_history": "qnh_im_messages",
    "channels": "qnh_traffic_channels",
}


class IngestRequest(BaseModel):
    source: str
    data: list[dict[str, Any]]
    synced_at: str | None = None
    api_key: str | None = None


class IngestResponse(BaseModel):
    ok: bool
    records: int
    source: str
    message: str = ""


def _verify_key(api_key: str | None, header_key: str | None) -> None:
    """验证 API key。"""
    if not SYNC_API_KEY:
        return  # 未配置则跳过
    key = header_key or api_key
    if key != SYNC_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid sync API key")


@router.post("/ingest", response_model=IngestResponse)
async def ingest_data(
    req: IngestRequest,
    x_sync_key: str | None = Header(None),
) -> IngestResponse:
    """接收并存储同步数据。

    本地 daemon 抓取 QNH 数据后 POST 到这里，后端直接写入对应 DB 表。
    """
    _verify_key(req.api_key, x_sync_key)

    if req.source not in SOURCE_TABLE_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown source: {req.source}")

    if not req.data:
        return IngestResponse(ok=True, records=0, source=req.source, message="empty data")

    table = SOURCE_TABLE_MAP[req.source]
    pool = await get_pool()
    synced_at = req.synced_at or datetime.now(UTC).isoformat()

    try:
        count = await _insert_records(pool, table, req.source, req.data, synced_at)
        logger.info("Ingested %d records into %s", count, table)
        return IngestResponse(ok=True, records=count, source=req.source)
    except Exception as e:
        logger.error("Ingest failed for %s: %s", req.source, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _insert_records(
    pool: Any,
    table: str,
    source: str,
    data: list[dict[str, Any]],
    synced_at: str,
) -> int:
    """将数据插入对应表。products 走结构化 upsert，其他走 raw JSONB。"""
    import json

    if source == "products":
        return await _upsert_products(pool, data)

    count = 0
    async with pool.acquire() as conn:
        for row in data:
            await conn.execute(
                f"""
                INSERT INTO {table}_raw (source, raw_data, synced_at)
                VALUES ($1, $2::jsonb, $3)
                """,
                source,
                json.dumps(row, ensure_ascii=False),
                synced_at,
            )
            count += 1

    return count


async def _upsert_products(pool: Any, data: list[dict[str, Any]]) -> int:
    """结构化 upsert 商品数据到 qnh_products。"""
    import json

    count = 0
    async with pool.acquire() as conn:
        for p in data:
            spu_id = str(p.get("spuId", p.get("spu_id", "")))
            if not spu_id:
                continue

            name = p.get("spuName") or p.get("name") or ""
            brand = ""
            if isinstance(p.get("brand"), dict):
                brand = p["brand"].get("brandName", "")
            elif isinstance(p.get("brand"), str):
                brand = p["brand"]

            pic_urls = p.get("picUrlList", p.get("pic_urls", []))
            if isinstance(pic_urls, str):
                try:
                    pic_urls = json.loads(pic_urls)
                except Exception:
                    pic_urls = []
            image_url = pic_urls[0] if pic_urls else p.get("image_url", "")

            skus = p.get("skus", [])
            if isinstance(skus, str):
                try:
                    skus = json.loads(skus)
                except Exception:
                    skus = []

            weight_type = p.get("weightTypeDesc", p.get("weight_type", ""))

            retail_price = p.get("retail_price")
            spec = p.get("spec", "")
            if not retail_price and skus and isinstance(skus, list):
                first_sku = skus[0] if skus else {}
                spec = spec or first_sku.get("specName", "")
                suggest = first_sku.get("suggestPrice", {})
                if isinstance(suggest, dict):
                    tp = suggest.get("tenantSuggestPrice", {})
                    if isinstance(tp, dict) and tp.get("unifiedSuggestPrice"):
                        with contextlib.suppress(ValueError, TypeError):
                            retail_price = float(tp["unifiedSuggestPrice"])

            status = p.get("status", "")
            if not status:
                status = "在售" if p.get("onlineStatus") == 1 else "停售"

            raw_sku = p.get("skuId") or p.get("sku_id") or ""
            sku_id = str(raw_sku) if raw_sku else ""

            await conn.execute(
                """
                INSERT INTO qnh_products (spu_id, sku_id, name, brand, spec, retail_price,
                    image_url, status, pic_urls, skus, weight_type, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, NOW())
                ON CONFLICT (spu_id, sku_id) DO UPDATE SET
                    name = EXCLUDED.name, brand = EXCLUDED.brand, spec = EXCLUDED.spec,
                    retail_price = EXCLUDED.retail_price, image_url = EXCLUDED.image_url,
                    status = EXCLUDED.status, pic_urls = EXCLUDED.pic_urls,
                    skus = EXCLUDED.skus, weight_type = EXCLUDED.weight_type, synced_at = NOW()
                """,
                spu_id,
                sku_id,
                name,
                brand,
                spec,
                retail_price,
                image_url,
                status,
                json.dumps(pic_urls, ensure_ascii=False),
                json.dumps(skus, ensure_ascii=False),
                weight_type,
            )
            count += 1

    return count


@router.get("/status")
async def sync_status() -> dict[str, Any]:
    """同步状态：最近同步时间和记录数。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        results = {}
        for source, table in SOURCE_TABLE_MAP.items():
            try:
                row = await conn.fetchrow(
                    f"SELECT COUNT(*) as cnt, MAX(synced_at) as last_sync FROM {table}_raw"
                )
                results[source] = {
                    "count": row["cnt"] if row else 0,
                    "last_sync": str(row["last_sync"]) if row and row["last_sync"] else None,
                }
            except Exception:
                results[source] = {"count": 0, "last_sync": None, "error": "table not found"}
        return {"sources": results}
