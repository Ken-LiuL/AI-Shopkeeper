"""Bundle Agent API routes."""

from __future__ import annotations

import json
import logging
import math

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import APIResponse, BundleGenerateRequest, BundleUpdateRequest, TaskCreatedResponse

router = APIRouter(prefix="/api/bundles", tags=["bundles"])
logger = logging.getLogger(__name__)


async def _build_order_based_bundle_recommendations(limit: int = 12) -> list[dict]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """
        WITH recent_order_items AS (
            SELECT
                oi.order_id,
                oi.product_id,
                SUM(oi.quantity) AS quantity
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE COALESCE(o.order_time, o.created_at) >= NOW() - INTERVAL '30 days'
            GROUP BY oi.order_id, oi.product_id
        ),
        product_orders AS (
            SELECT product_id, COUNT(*) AS order_count
            FROM recent_order_items
            GROUP BY product_id
        ),
        pair_orders AS (
            SELECT
                LEAST(a.product_id, b.product_id) AS product_a,
                GREATEST(a.product_id, b.product_id) AS product_b,
                COUNT(*) AS pair_order_count
            FROM recent_order_items a
            JOIN recent_order_items b
              ON a.order_id = b.order_id
             AND a.product_id < b.product_id
            GROUP BY 1, 2
            HAVING COUNT(*) >= 2
        )
        SELECT
            po.product_a,
            po.product_b,
            po.pair_order_count,
            poa.order_count AS product_a_orders,
            pob.order_count AS product_b_orders,
            p1.name AS name_a,
            p2.name AS name_b,
            COALESCE(p1.retail_price, 0) AS price_a,
            COALESCE(p2.retail_price, 0) AS price_b,
            COALESCE(p1.cost_price, 0) AS cost_a,
            COALESCE(p2.cost_price, 0) AS cost_b,
            COALESCE(p1.monthly_sales, 0) AS sales_a,
            COALESCE(p2.monthly_sales, 0) AS sales_b
        FROM pair_orders po
        JOIN product_orders poa ON poa.product_id = po.product_a
        JOIN product_orders pob ON pob.product_id = po.product_b
        JOIN products p1 ON p1.product_id = po.product_a
        JOIN products p2 ON p2.product_id = po.product_b
        WHERE COALESCE(p1.retail_price, 0) > 0
          AND COALESCE(p2.retail_price, 0) > 0
          AND COALESCE(p1.status, 'active') = 'active'
          AND COALESCE(p2.status, 'active') = 'active'
        ORDER BY po.pair_order_count DESC, (COALESCE(p1.monthly_sales, 0) + COALESCE(p2.monthly_sales, 0)) DESC
        LIMIT $1
        """,
        limit,
    )

    bundles: list[dict] = []
    for row in rows:
        pair_orders = int(row["pair_order_count"] or 0)
        price_a = float(row["price_a"] or 0)
        price_b = float(row["price_b"] or 0)
        cost_a = float(row["cost_a"] or 0)
        cost_b = float(row["cost_b"] or 0)
        base_total = price_a + price_b
        if base_total <= 0:
            continue

        order_a = max(1, int(row["product_a_orders"] or 0))
        order_b = max(1, int(row["product_b_orders"] or 0))
        lift_value = round(pair_orders / max(1.0, math.sqrt(order_a * order_b)), 2)
        confidence = round(min(0.95, 0.45 + pair_orders / 20 + lift_value * 0.08), 2)

        discount = 0.08 if pair_orders >= 5 else 0.05
        bundle_price = round(base_total * (1 - discount), 2)
        estimated_profit_margin = None
        if cost_a > 0 and cost_b > 0 and bundle_price > 0:
            estimated_profit_margin = round(
                max(0.0, (bundle_price - cost_a - cost_b) / bundle_price * 100),
                1,
            )

        bundles.append(
            {
                "id": f"bundle:{row['product_a']}:{row['product_b']}",
                "name": f"{row['name_a']} + {row['name_b']}",
                "product_ids": [row["product_a"], row["product_b"]],
                "products": [
                    {
                        "product_id": row["product_a"],
                        "name": row["name_a"],
                        "unit_price": round(price_a, 2),
                        "monthly_sales": int(row["sales_a"] or 0),
                    },
                    {
                        "product_id": row["product_b"],
                        "name": row["name_b"],
                        "unit_price": round(price_b, 2),
                        "monthly_sales": int(row["sales_b"] or 0),
                    },
                ],
                "confidence": confidence,
                "lift_value": lift_value,
                "bundle_price": bundle_price,
                "estimated_profit_margin": estimated_profit_margin,
                "pair_orders": pair_orders,
                "reason": f"近 30 天有 {pair_orders} 单同时购买，适合做套餐试卖",
                "data_source": "近30天订单共购",
            }
        )
    return bundles


@router.get("/recommendations", response_model=APIResponse[list[dict]])
async def bundle_recommendations() -> APIResponse[list[dict]]:
    """套餐推荐 — 优先基于真实订单共购关系。"""
    try:
        bundles = await _build_order_based_bundle_recommendations()
        return APIResponse(
            data=bundles,
            message=f"基于近 30 天订单共购生成 {len(bundles)} 个套餐候选" if bundles else "近 30 天订单共购不足，暂时无法生成可信套餐",
        )
    except Exception as e:
        logger.exception("Bundle recommendations failed")
        return APIResponse(data=[], message=f"推荐生成失败: {e}")


# UNUSED: no frontend caller
@router.get("/suggestions", response_model=APIResponse[list[dict]])
async def bundle_suggestions() -> APIResponse[list[dict]]:
    """套餐建议 — /recommendations 的别名"""
    return await bundle_recommendations()


# UNUSED: no frontend caller
@router.get("/{bundle_id}", response_model=APIResponse[dict])
async def get_bundle(bundle_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow("SELECT * FROM bundles WHERE bundle_id = $1", bundle_id)
        if not row:
            raise NotFoundError("Bundle", bundle_id)
        return APIResponse(data=dict(row))
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to get bundle %s: %s", bundle_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# UNUSED: no frontend caller
@router.post("/{bundle_id}/activate", response_model=APIResponse[dict])
async def activate_bundle(bundle_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "UPDATE bundles SET status = 'active' WHERE bundle_id = $1 RETURNING *",
            bundle_id,
        )
        if not row:
            raise NotFoundError("Bundle", bundle_id)
        return APIResponse(data=dict(row), message="Bundle activated")
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to activate bundle %s: %s", bundle_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# UNUSED: no frontend caller
@router.post("/{bundle_id}/deactivate", response_model=APIResponse[dict])
async def deactivate_bundle(bundle_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "UPDATE bundles SET status = 'inactive' WHERE bundle_id = $1 RETURNING *",
            bundle_id,
        )
        if not row:
            raise NotFoundError("Bundle", bundle_id)
        return APIResponse(data=dict(row), message="Bundle deactivated")
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to deactivate bundle %s: %s", bundle_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# UNUSED: no frontend caller
@router.get("", response_model=APIResponse[list[dict]])
async def list_bundles() -> APIResponse[list[dict]]:
    try:
        pool = pg.get_pool()
        rows = await pool.fetch(
            "SELECT * FROM bundles WHERE status != 'deleted' ORDER BY created_at DESC"
        )
        if not rows:
            return APIResponse(data=[], message="功能待开通")
        return APIResponse(data=[dict(r) for r in rows])
    except Exception as exc:
        logger.error("Failed to list bundles: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


async def _run_bundle_generate(
    task_id: str, request: BundleGenerateRequest, orch: Orchestrator
) -> None:
    try:
        kwargs = {k: v for k, v in request.model_dump().items() if v is not None}
        pool = pg.get_pool()
        result = await orch.run_bundle(db_pool=pool, **kwargs)
        await pool.execute(
            "UPDATE bundle_tasks SET status = 'completed', result = $1::jsonb, finished_at = NOW() WHERE task_id = $2",
            json.dumps(result, default=str),
            task_id,
        )
    except Exception:
        logger.exception("Bundle generate %s failed", task_id)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE bundle_tasks SET status = 'failed', finished_at = NOW() WHERE task_id = $1",
            task_id,
        )


# UNUSED: no frontend caller
@router.post("/generate", response_model=TaskCreatedResponse)
async def generate_bundles(
    request: BundleGenerateRequest,
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> TaskCreatedResponse:
    try:
        task_id = gen_id("bnd_")
        pool = pg.get_pool()
        await pool.execute(
            "INSERT INTO bundle_tasks (task_id, status, created_at) VALUES ($1, 'running', NOW())",
            task_id,
        )
        bg.add_task(_run_bundle_generate, task_id, request, orch)
        return TaskCreatedResponse(task_id=task_id, message="Bundle generation started")
    except Exception as exc:
        logger.error("Failed to create bundle task: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# UNUSED: no frontend caller
@router.patch("/{bundle_id}", response_model=APIResponse[dict])
async def update_bundle(bundle_id: str, body: BundleUpdateRequest) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise NotFoundError("Bundle", bundle_id)

        set_clauses = [f"{k} = ${i + 1}" for i, k in enumerate(updates)]
        params = list(updates.values()) + [bundle_id]
        row = await pool.fetchrow(
            f"UPDATE bundles SET {', '.join(set_clauses)} WHERE bundle_id = ${len(params)} RETURNING *",
            *params,
        )
        if not row:
            raise NotFoundError("Bundle", bundle_id)
        return APIResponse(data=dict(row))
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to update bundle %s: %s", bundle_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


# UNUSED: no frontend caller
@router.delete("/{bundle_id}", response_model=APIResponse[dict])
async def delete_bundle(bundle_id: str) -> APIResponse[dict]:
    try:
        pool = pg.get_pool()
        row = await pool.fetchrow(
            "UPDATE bundles SET status = 'deleted' WHERE bundle_id = $1 RETURNING *",
            bundle_id,
        )
        if not row:
            raise NotFoundError("Bundle", bundle_id)
        return APIResponse(data=dict(row), message="Bundle deleted")
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to delete bundle %s: %s", bundle_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
