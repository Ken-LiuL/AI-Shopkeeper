"""AI Insights API - 智能经营洞察"""

from __future__ import annotations

import json
import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import Any

import asyncio

from fastapi import APIRouter, BackgroundTasks, Query

from src.agents.llm import MODEL_DEEPSEEK, MODEL_HAIKU, call_tool
from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/insights", tags=["insights"])
logger = logging.getLogger(__name__)

# Cache configuration
CACHE_DIR = os.path.expanduser("~/.openclaw/workspace-code/cache")
CACHE_TTL_HOURS = 1


def _get_cache_key(target_date: datetime) -> str:
    """生成缓存键"""
    return f"daily_insights_{target_date.date().isoformat()}"


def _get_cache_file_path(cache_key: str) -> str:
    """获取缓存文件路径"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.pkl")


def _load_from_cache(cache_key: str) -> dict[str, Any] | None:
    """从缓存加载数据"""
    cache_file = _get_cache_file_path(cache_key)

    try:
        if os.path.exists(cache_file):
            with open(cache_file, "rb") as f:
                cached_data = pickle.load(f)

            # 检查TTL
            cache_time = datetime.fromisoformat(cached_data.get("cached_at", ""))
            if datetime.now() - cache_time < timedelta(hours=CACHE_TTL_HOURS):
                logger.info(f"Cache hit for {cache_key}")
                return cached_data.get("data")
            else:
                # 缓存过期，删除文件
                os.remove(cache_file)
                logger.info(f"Cache expired for {cache_key}, removed file")
    except Exception as e:
        logger.warning(f"Failed to load cache {cache_key}: {e}")
        # 删除损坏的缓存文件
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
        except Exception:
            pass

    return None


def _save_to_cache(cache_key: str, data: dict[str, Any]) -> None:
    """保存数据到缓存"""
    cache_file = _get_cache_file_path(cache_key)

    try:
        cached_data = {"cached_at": datetime.now().isoformat(), "data": data}

        with open(cache_file, "wb") as f:
            pickle.dump(cached_data, f)

        logger.info(f"Cached data for {cache_key}")
    except Exception as e:
        logger.warning(f"Failed to save cache {cache_key}: {e}")


async def _get_daily_business_data(target_date: datetime = None) -> dict[str, Any]:
    """获取指定日期的业务数据"""
    if not target_date:
        target_date = datetime.now()

    pool = pg.get_pool()

    # 获取基础指标
    today = target_date.date()
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)

    business_data = {
        "date": str(today),
        "orders": {},
        "products": {},
        "categories": {},
        "competitors": {},
        "trends": {},
    }

    try:
        # 订单数据
        order_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as today_orders,
                COALESCE(SUM(total_amount), 0) as today_gmv,
                COALESCE(AVG(total_amount), 0) as avg_order_value
            FROM orders
            WHERE DATE(order_time) = $1
        """,
            today,
        )

        yesterday_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as yesterday_orders,
                COALESCE(SUM(total_amount), 0) as yesterday_gmv
            FROM orders
            WHERE DATE(order_time) = $1
        """,
            yesterday,
        )

        business_data["orders"] = {
            "today_count": int(order_stats["today_orders"]) if order_stats["today_orders"] else 0,
            "today_gmv": float(order_stats["today_gmv"]) if order_stats["today_gmv"] else 0,
            "avg_order_value": float(order_stats["avg_order_value"])
            if order_stats["avg_order_value"]
            else 0,
            "yesterday_count": int(yesterday_stats["yesterday_orders"])
            if yesterday_stats["yesterday_orders"]
            else 0,
            "yesterday_gmv": float(yesterday_stats["yesterday_gmv"])
            if yesterday_stats["yesterday_gmv"]
            else 0,
            "growth_rate": 0,
        }

        # 计算增长率
        if business_data["orders"]["yesterday_gmv"] > 0:
            business_data["orders"]["growth_rate"] = (
                business_data["orders"]["today_gmv"] / business_data["orders"]["yesterday_gmv"] - 1
            ) * 100

    except Exception as e:
        logger.warning(f"Failed to get order stats: {e}")

    try:
        # 热销商品
        top_products = await pool.fetch(
            """
            SELECT
                p.name,
                p.category,
                SUM(oi.quantity) as total_sold,
                SUM(oi.quantity * oi.unit_price) as revenue,
                COUNT(DISTINCT oi.order_id) as order_count
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE DATE(o.order_time) = $1
            GROUP BY p.product_id, p.name, p.category
            ORDER BY total_sold DESC
            LIMIT 10
        """,
            today,
        )

        business_data["products"]["top_selling"] = [
            {
                "name": row["name"],
                "category": row["category"],
                "quantity_sold": int(row["total_sold"]),
                "revenue": float(row["revenue"]),
                "order_count": int(row["order_count"]),
            }
            for row in top_products
        ]

    except Exception as e:
        logger.warning(f"Failed to get product stats: {e}")
        business_data["products"]["top_selling"] = []

    try:
        # 品类表现
        category_performance = await pool.fetch(
            """
            SELECT
                p.category,
                SUM(oi.quantity) as total_sold,
                SUM(oi.quantity * oi.unit_price) as revenue,
                COUNT(DISTINCT p.product_id) as product_count
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE DATE(o.order_time) = $1
            GROUP BY p.category
            ORDER BY revenue DESC
        """,
            today,
        )

        business_data["categories"] = {
            "performance": [
                {
                    "category": row["category"],
                    "total_sold": int(row["total_sold"]),
                    "revenue": float(row["revenue"]),
                    "product_count": int(row["product_count"]),
                }
                for row in category_performance
            ]
        }

    except Exception as e:
        logger.warning(f"Failed to get category stats: {e}")
        business_data["categories"] = {"performance": []}

    try:
        # 竞品动态
        competitor_changes = await pool.fetch(
            """
            SELECT
                competitor_name,
                product_name,
                price,
                previous_price,
                price_change_percent,
                updated_at
            FROM competitor_products
            WHERE DATE(updated_at) = $1 AND ABS(price_change_percent) > 5
            ORDER BY ABS(price_change_percent) DESC
            LIMIT 10
        """,
            today,
        )

        business_data["competitors"]["price_changes"] = [
            {
                "competitor": row["competitor_name"],
                "product": row["product_name"],
                "current_price": float(row["price"]),
                "previous_price": float(row["previous_price"]) if row["previous_price"] else 0,
                "change_percent": float(row["price_change_percent"])
                if row["price_change_percent"]
                else 0,
            }
            for row in competitor_changes
        ]

    except Exception as e:
        logger.warning(f"Failed to get competitor data: {e}")
        business_data["competitors"]["price_changes"] = []

    try:
        # 7天趋势
        trend_data = await pool.fetch(
            """
            SELECT
                DATE(order_time) as date,
                COUNT(*) as order_count,
                SUM(total_amount) as gmv
            FROM orders
            WHERE order_time >= $1
            GROUP BY DATE(order_time)
            ORDER BY date
        """,
            last_week,
        )

        business_data["trends"]["weekly"] = [
            {
                "date": str(row["date"]),
                "order_count": int(row["order_count"]),
                "gmv": float(row["gmv"]),
            }
            for row in trend_data
        ]

    except Exception as e:
        logger.warning(f"Failed to get trend data: {e}")
        business_data["trends"]["weekly"] = []

    # 从raw数据补充信息
    try:
        raw_data = await _get_raw_business_data(today)
        if raw_data:
            business_data.update(raw_data)
    except Exception as e:
        logger.warning(f"Failed to get raw business data: {e}")

    return business_data


async def _get_raw_business_data(target_date) -> dict[str, Any]:
    """从raw表获取补充业务数据"""
    pool = pg.get_pool()
    raw_data = {"raw_metrics": {}, "raw_orders": {}}

    try:
        # 获取最新的指标数据
        metrics_row = await pool.fetchrow(
            """
            SELECT raw_data, synced_at
            FROM qnh_store_metrics_raw
            WHERE DATE(created_at) = $1
            ORDER BY created_at DESC
            LIMIT 1
        """,
            target_date,
        )

        if metrics_row:
            metrics = metrics_row["raw_data"]
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            raw_data["raw_metrics"] = metrics
    except Exception as e:
        logger.warning(f"Failed to get raw metrics: {e}")

    try:
        # 获取订单raw数据
        orders_row = await pool.fetchrow(
            """
            SELECT raw_data, synced_at
            FROM qnh_orders_raw
            WHERE DATE(created_at) = $1
            ORDER BY created_at DESC
            LIMIT 1
        """,
            target_date,
        )

        if orders_row:
            orders = orders_row["raw_data"]
            if isinstance(orders, str):
                orders = json.loads(orders)
            raw_data["raw_orders"] = orders
    except Exception as e:
        logger.warning(f"Failed to get raw orders: {e}")

    return raw_data


async def _generate_ai_insights(business_data: dict[str, Any]) -> dict[str, Any]:
    """使用AI生成经营洞察"""

    # 获取外部因素（天气、节假日等）
    today = datetime.now()
    external_factors = {
        "date": str(today.date()),
        "weekday": today.strftime("%A"),
        "is_weekend": today.weekday() >= 5,
        "season": _get_season(today),
        # "weather": "晴天",  # 可以接入天气API
    }

    prompt = f"""
    你是AI店长，负责分析医疗器械店铺的每日经营数据，生成具体可操作的经营洞察。

    ## 今日业务数据
    {json.dumps(business_data, ensure_ascii=False, indent=2)}

    ## 外部因素
    {json.dumps(external_factors, ensure_ascii=False, indent=2)}

    请从以下维度进行深度分析：

    1. **销售异常检测**：识别环比大涨/大跌的品类和商品，分析原因
    2. **热销商品变化**：对比热销商品排行变化，发现新趋势
    3. **竞品动态分析**：分析竞品价格变化对我们的影响
    4. **外部因素影响**：天气、节假日、季节对销量的影响
    5. **具体操作建议**：给出明天可执行的3-5条具体建议

    要求：
    - 数据驱动，有具体数字支撑
    - 避免空泛建议，给出可操作的具体动作
    - 识别机会和风险
    - 考虑医疗器械行业特点
    """

    tool = {
        "name": "generate_business_insights",
        "description": "生成AI经营洞察",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "今日经营情况总结"},
                "anomaly_detection": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                            "impact": {"type": "string"},
                            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        },
                    },
                },
                "trending_products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product": {"type": "string"},
                            "trend": {"type": "string", "enum": ["rising", "falling", "stable"]},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "competitor_analysis": {
                    "type": "object",
                    "properties": {
                        "key_changes": {"type": "array", "items": {"type": "string"}},
                        "opportunities": {"type": "array", "items": {"type": "string"}},
                        "threats": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "external_impact": {
                    "type": "object",
                    "properties": {
                        "weather_impact": {"type": "string"},
                        "seasonal_factors": {"type": "string"},
                        "market_trends": {"type": "string"},
                    },
                },
                "actionable_recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "expected_impact": {"type": "string"},
                            "timeline": {"type": "string"},
                        },
                        "required": ["action", "priority", "expected_impact"],
                    },
                },
                "key_metrics": {
                    "type": "object",
                    "properties": {
                        "performance_score": {"type": "number", "minimum": 0, "maximum": 100},
                        "growth_outlook": {
                            "type": "string",
                            "enum": ["positive", "neutral", "negative"],
                        },
                        "risk_level": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                },
            },
            "required": ["summary", "actionable_recommendations", "key_metrics"],
        },
    }

    try:
        # 优先使用更快的模型（Haiku 速度更快），若失败降级到 DeepSeek
        try:
            result = await call_tool(
                prompt=prompt,
                tool=tool,
                model=MODEL_HAIKU,
                max_tokens=2000,
                trace_name="daily_business_insights",
            )
        except Exception:
            result = await call_tool(
                prompt=prompt,
                tool=tool,
                model=MODEL_DEEPSEEK,
                max_tokens=4000,
                trace_name="daily_business_insights",
            )

        return result
    except Exception as e:
        logger.error(f"AI insights generation failed: {e}")
        return {
            "summary": "数据分析中遇到问题，无法生成详细洞察",
            "actionable_recommendations": [
                {
                    "action": "检查数据收集系统状态",
                    "priority": "high",
                    "expected_impact": "恢复正常分析功能",
                    "timeline": "立即执行",
                }
            ],
            "key_metrics": {
                "performance_score": 50,
                "growth_outlook": "neutral",
                "risk_level": "medium",
            },
        }


def _get_season(date: datetime) -> str:
    """获取季节"""
    month = date.month
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:
        return "autumn"


async def _async_generate_and_cache(cache_key: str, target_date: datetime) -> None:
    """后台异步生成 AI 洞察并写入缓存"""
    try:
        business_data = await _get_daily_business_data(target_date)
        insights = await _generate_ai_insights(business_data)
        result = {
            "analysis_date": str(target_date.date()),
            "generated_at": datetime.now().isoformat(),
            "business_data": business_data,
            "ai_insights": insights,
            "data_completeness": _calculate_data_completeness(business_data),
            "from_cache": False,
            "cache_key": cache_key,
            "status": "ready",
        }
        _save_to_cache(cache_key, result)
        logger.info(f"Background insights generation completed for {cache_key}")
    except Exception as e:
        logger.error(f"Background insights generation failed: {e}")


@router.get("/daily", response_model=APIResponse[dict])
async def get_daily_insights(
    background_tasks: BackgroundTasks,
    date: str = Query(None, description="分析日期 YYYY-MM-DD，默认今天"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
) -> APIResponse[dict]:
    """AI生成的每日经营洞察（带缓存）"""

    try:
        # 解析日期
        target_date = datetime.now()
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return APIResponse(
                    success=False, message="日期格式错误，请使用YYYY-MM-DD格式", data={}
                )

        # 生成缓存键
        cache_key = _get_cache_key(target_date)

        # 尝试从缓存加载（除非强制刷新）
        if not force_refresh:
            cached_result = _load_from_cache(cache_key)
            if cached_result:
                # 添加缓存标识
                cached_result["from_cache"] = True
                cached_result["cache_key"] = cache_key
                return APIResponse(data=cached_result)

        # 缓存未命中或强制刷新 — 异步后台生成，立即返回"生成中"状态
        logger.info(f"Cache miss for {cache_key}, dispatching background generation")
        background_tasks.add_task(_async_generate_and_cache, cache_key, target_date)

        return APIResponse(
            data={
                "analysis_date": str(target_date.date()),
                "generated_at": datetime.now().isoformat(),
                "status": "generating",
                "message": "AI 洞察正在后台生成，通常需要 10-20 秒，请稍后重新请求（将命中缓存直接返回）",
                "from_cache": False,
                "cache_key": cache_key,
            }
        )

    except Exception as e:
        logger.error(f"Failed to generate daily insights: {e}")
        return APIResponse(success=False, message=f"生成洞察失败: {str(e)}", data={})


def _calculate_data_completeness(business_data: dict[str, Any]) -> dict[str, Any]:
    """计算数据完整度"""
    completeness = {
        "order_data": bool(business_data.get("orders", {}).get("today_count", 0) > 0),
        "product_data": bool(business_data.get("products", {}).get("top_selling")),
        "category_data": bool(business_data.get("categories", {}).get("performance")),
        "competitor_data": bool(business_data.get("competitors", {}).get("price_changes")),
        "trend_data": bool(business_data.get("trends", {}).get("weekly")),
    }

    total_score = sum(completeness.values()) / len(completeness) * 100

    return {
        "individual_scores": completeness,
        "overall_score": round(total_score, 1),
        "missing_data": [k for k, v in completeness.items() if not v],
    }


@router.get("/weekly-summary", response_model=APIResponse[dict])
async def get_weekly_summary() -> APIResponse[dict]:
    """本周经营总结"""

    try:
        pool = pg.get_pool()

        # 本周数据
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())

        weekly_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as total_orders,
                SUM(total_amount) as total_gmv,
                AVG(total_amount) as avg_order_value,
                COUNT(DISTINCT DATE(order_time)) as active_days
            FROM orders
            WHERE DATE(order_time) >= $1
        """,
            week_start,
        )

        # 日均对比
        daily_breakdown = await pool.fetch(
            """
            SELECT
                DATE(order_time) as date,
                COUNT(*) as orders,
                SUM(total_amount) as gmv
            FROM orders
            WHERE DATE(order_time) >= $1
            GROUP BY DATE(order_time)
            ORDER BY date
        """,
            week_start,
        )

        # 热销品类
        top_categories = await pool.fetch(
            """
            SELECT
                p.category,
                SUM(oi.quantity) as total_sold,
                SUM(oi.quantity * oi.unit_price) as revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE DATE(o.order_time) >= $1
            GROUP BY p.category
            ORDER BY revenue DESC
            LIMIT 5
        """,
            week_start,
        )

        result = {
            "week_period": f"{week_start} 至 {today}",
            "overall_performance": {
                "total_orders": int(weekly_stats["total_orders"])
                if weekly_stats["total_orders"]
                else 0,
                "total_gmv": float(weekly_stats["total_gmv"]) if weekly_stats["total_gmv"] else 0,
                "avg_order_value": float(weekly_stats["avg_order_value"])
                if weekly_stats["avg_order_value"]
                else 0,
                "active_days": int(weekly_stats["active_days"])
                if weekly_stats["active_days"]
                else 0,
            },
            "daily_breakdown": [
                {"date": str(row["date"]), "orders": int(row["orders"]), "gmv": float(row["gmv"])}
                for row in daily_breakdown
            ],
            "top_categories": [
                {
                    "category": row["category"],
                    "units_sold": int(row["total_sold"]),
                    "revenue": float(row["revenue"]),
                }
                for row in top_categories
            ],
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to generate weekly summary: {e}")
        return APIResponse(success=False, message=f"生成周总结失败: {str(e)}", data={})


@router.get("/alerts", response_model=APIResponse[list[dict]])
async def get_business_alerts() -> APIResponse[list[dict]]:
    """业务异常预警"""

    try:
        alerts = []
        pool = pg.get_pool()

        # 检查订单异常
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        today_orders = await pool.fetchval(
            "SELECT COUNT(*) FROM orders WHERE DATE(order_time) = $1", today
        )
        yesterday_orders = await pool.fetchval(
            "SELECT COUNT(*) FROM orders WHERE DATE(order_time) = $1", yesterday
        )

        if yesterday_orders > 0:
            change_rate = (today_orders - yesterday_orders) / yesterday_orders * 100
            if change_rate < -30:
                alerts.append(
                    {
                        "type": "order_drop",
                        "severity": "high",
                        "message": f"今日订单量较昨日下降{abs(change_rate):.1f}%",
                        "data": {"today": today_orders, "yesterday": yesterday_orders},
                    }
                )
            elif change_rate > 50:
                alerts.append(
                    {
                        "type": "order_surge",
                        "severity": "medium",
                        "message": f"今日订单量较昨日增长{change_rate:.1f}%",
                        "data": {"today": today_orders, "yesterday": yesterday_orders},
                    }
                )

        # 检查库存预警
        low_stock = await pool.fetch("""
            SELECT product_id, name, stock
            FROM products
            WHERE status = 'active' AND stock <= 5
            ORDER BY stock
        """)

        if low_stock:
            alerts.append(
                {
                    "type": "low_inventory",
                    "severity": "high",
                    "message": f"{len(low_stock)}个商品库存不足",
                    "data": [{"name": row["name"], "stock": row["stock"]} for row in low_stock],
                }
            )

        # 检查竞品价格变动
        price_changes = await pool.fetch(
            """
            SELECT competitor_name, product_name, price_change_percent
            FROM competitor_products
            WHERE DATE(updated_at) = $1 AND ABS(price_change_percent) > 10
            ORDER BY ABS(price_change_percent) DESC
            LIMIT 5
        """,
            today,
        )

        if price_changes:
            alerts.append(
                {
                    "type": "competitor_price_change",
                    "severity": "medium",
                    "message": f"检测到{len(price_changes)}个竞品大幅调价",
                    "data": [
                        {
                            "competitor": row["competitor_name"],
                            "product": row["product_name"],
                            "change": float(row["price_change_percent"]),
                        }
                        for row in price_changes
                    ],
                }
            )

        return APIResponse(data=alerts)

    except Exception as e:
        logger.error(f"Failed to generate business alerts: {e}")
        return APIResponse(success=False, message=f"生成预警失败: {str(e)}", data=[])
