"""Store configuration management for Meituan YiYao sync."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from src.api.schemas import APIResponse
from src.db import postgres as pg
from src.sync.meituan_client import MeituanBrowserClient
from src.sync.meituan_products import MeituanProductSyncer

router = APIRouter(prefix="/api/stores", tags=["store-configs"])
logger = logging.getLogger(__name__)

CookiePayload = dict[str, Any] | list[Any] | str | None


class StoreConfigOut(BaseModel):
    id: int
    store_name: str
    platform: str
    poi_id: str | None = None
    account: str | None = None
    wm_poi_id: str | None = None
    region_id: str | None = None
    region_version: str | None = None
    sync_status: str | None = None
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    cookie_json: Any | None = None


class StoreConfigCreateRequest(BaseModel):
    store_name: str = Field(..., max_length=200)
    account: str = Field(..., max_length=100)
    password: str = Field(..., min_length=1)
    poi_id: str = Field(..., max_length=50)
    wm_poi_id: str = Field(..., max_length=50)
    cookie_json: CookiePayload = None
    region_id: str | None = Field(default=None, max_length=50)
    region_version: str | None = Field(default=None, max_length=50)


class StoreConfigUpdateRequest(BaseModel):
    store_name: str | None = Field(default=None, max_length=200)
    account: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, min_length=1)
    poi_id: str | None = Field(default=None, max_length=50)
    wm_poi_id: str | None = Field(default=None, max_length=50)
    cookie_json: CookiePayload = None
    region_id: str | None = Field(default=None, max_length=50)
    region_version: str | None = Field(default=None, max_length=50)
    sync_status: str | None = Field(default=None, max_length=20)


@router.get("/overview", response_model=APIResponse)
async def get_stores_overview_alias():
    """路由别名 — 前端调 /stores/overview，转发到 /store/overview 的 handler"""
    from src.api.stores import get_stores_overview

    return await get_stores_overview()


@router.get("", response_model=APIResponse[list[StoreConfigOut]])
async def list_store_configs() -> APIResponse[list[StoreConfigOut]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """
        SELECT id, store_name, platform, poi_id, account, wm_poi_id,
               region_id, region_version, sync_status, last_sync_at,
               last_sync_error, created_at, updated_at, cookie_json
        FROM store_configs
        ORDER BY id ASC
        """
    )
    data = [_row_to_config(row) for row in rows]
    return APIResponse(data=data)


@router.post("", response_model=APIResponse[StoreConfigOut])
async def create_store_config(body: StoreConfigCreateRequest) -> APIResponse[StoreConfigOut]:
    pool = pg.get_pool()
    encrypted = _encode_password(body.password)
    cookie_blob = _serialize_cookie_json(body.cookie_json)

    row = await pool.fetchrow(
        """
        INSERT INTO store_configs
            (store_name, account, password_encrypted, poi_id, wm_poi_id,
             cookie_json, region_id, region_version)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        RETURNING id, store_name, platform, poi_id, account, wm_poi_id,
                  region_id, region_version, sync_status, last_sync_at,
                  last_sync_error, created_at, updated_at, cookie_json
        """,
        body.store_name,
        body.account,
        encrypted,
        body.poi_id,
        body.wm_poi_id,
        cookie_blob,
        body.region_id,
        body.region_version,
    )
    return APIResponse(data=_row_to_config(row))


@router.put("/{config_id}", response_model=APIResponse[StoreConfigOut])
async def update_store_config(
    body: StoreConfigUpdateRequest,
    config_id: int = Path(..., ge=1),
) -> APIResponse[StoreConfigOut]:
    pool = pg.get_pool()
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="没有可更新的字段")

    fields: list[str] = []
    values: list[Any] = []

    for field, value in payload.items():
        if field == "password":
            fields.append("password_encrypted")
            values.append(_encode_password(value))
        elif field == "cookie_json":
            fields.append("cookie_json")
            values.append(_serialize_cookie_json(value))
        else:
            fields.append(field)
            values.append(value)

    set_clause = ", ".join(f"{field} = ${idx + 1}" for idx, field in enumerate(fields))
    values.append(config_id)
    row = await pool.fetchrow(
        f"""
        UPDATE store_configs
        SET {set_clause}, updated_at = NOW()
        WHERE id = ${len(values)}
        RETURNING id, store_name, platform, poi_id, account, wm_poi_id,
                  region_id, region_version, sync_status, last_sync_at,
                  last_sync_error, created_at, updated_at, cookie_json
        """,
        *values,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Store config not found")
    return APIResponse(data=_row_to_config(row))


@router.delete("/{config_id}", response_model=APIResponse[dict])
async def delete_store_config(config_id: int = Path(..., ge=1)) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "DELETE FROM store_configs WHERE id = $1 RETURNING id",
        config_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Store config not found")
    return APIResponse(data={"deleted": row["id"]})


@router.post("/{config_id}/sync", response_model=APIResponse[dict])
async def trigger_store_sync(config_id: int = Path(..., ge=1)) -> APIResponse[dict]:
    pool = pg.get_pool()
    config_row = await pool.fetchrow("SELECT * FROM store_configs WHERE id = $1", config_id)
    if not config_row:
        raise HTTPException(status_code=404, detail="Store config not found")
    config = dict(config_row)
    wm_poi_id = config.get("wm_poi_id")
    if not wm_poi_id:
        raise HTTPException(status_code=400, detail="wm_poi_id 未配置")

    cookie_json = config.get("cookie_json")
    client = MeituanBrowserClient(cookie_json=cookie_json, wm_poi_id=wm_poi_id)
    syncer = MeituanProductSyncer(client=client, db_pool=pool, wm_poi_id=wm_poi_id)

    try:
        result = await syncer.full_sync()
    except Exception as exc:  # noqa: BLE001
        logger.error("手动同步失败: %s", exc, exc_info=True)
        await pool.execute(
            """
            UPDATE store_configs
            SET sync_status = 'error', last_sync_error = $2, updated_at = NOW()
            WHERE id = $1
            """,
            config_id,
            str(exc),
        )
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc
    finally:
        await client.close()

    await pool.execute(
        """
        UPDATE store_configs
        SET sync_status = CASE WHEN $2 THEN 'active' ELSE 'error' END,
            last_sync_at = NOW(),
            last_sync_error = $3,
            updated_at = NOW()
        WHERE id = $1
        """,
        config_id,
        result.success,
        result.error,
    )

    return APIResponse(
        data={
            "success": result.success,
            "records_synced": result.records_synced,
            "error": result.error,
        }
    )


def _row_to_config(row: Any) -> StoreConfigOut:
    data = dict(row)
    parsed_cookie = _deserialize_cookie_json(data.get("cookie_json"))
    return StoreConfigOut(
        id=data["id"],
        store_name=data["store_name"],
        platform=data["platform"],
        poi_id=data["poi_id"],
        account=data["account"],
        wm_poi_id=data["wm_poi_id"],
        region_id=data["region_id"],
        region_version=data["region_version"],
        sync_status=data["sync_status"],
        last_sync_at=data["last_sync_at"],
        last_sync_error=data["last_sync_error"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        cookie_json=parsed_cookie,
    )


def _encode_password(raw: str | None) -> str | None:
    if raw is None:
        return None
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _serialize_cookie_json(payload: CookiePayload) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        cleaned = payload.strip()
        return cleaned or None
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid cookie_json: {exc}") from exc


def _deserialize_cookie_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
