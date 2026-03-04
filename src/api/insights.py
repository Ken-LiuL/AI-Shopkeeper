"""AI Insights API - 智能经营洞察"""

from __future__ import annotations

import json
import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import Any

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
    """获取指定日期的业务数据 — 优先从 qnh_dataset_records 读取真实数据。"""
    import re

    if not target_date:
        target_date = datetime.now()

    pool = pg.get_pool()
    today = target_date.date()

    def _pv(field) -> float:
        if field is None:
            return 0.0
        if isinstance(field, int | float):
            return float(field)
        if isinstance(field, dict):
            raw = field.get("dataValue", "")
        else:
            raw = str(field)
        if not raw:
            return 0.0
        cleaned = re.sub(r"[,%\s]", "", str(raw))
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    def _sv(field) -> str:
        if field is None:
            return ""
        if isinstance(field, str):
            return field
        if isinstance(field, dict):
            return str(field.get("dataValue", ""))
        return str(field)

    business_data: dict[str, Any] = {
        "date": str(today),
        "orders": {},
        "products": {},
        "categories": {},
        "competitors": {},
        "trends": {},
        "raw_metrics": {},
        "raw_orders": {},
    }

    # ── Priority 1: qnh_dataset_records (store_rank + hotsale_goods) ──
    try:
        store_rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset = 'store_rank'"
        )
        if store_rows:
            total_orders = 0
            total_gmv = 0.0
            total_customers = 0
            total_profit = 0.0
            for row in store_rows:
                p = row["payload"]
                if isinstance(p, str):
                    p = json.loads(p)
                total_orders += int(_pv(p.get("eff_ord_cnt")))
                total_gmv += _pv(p.get("sale_amt_gmv"))
                total_customers += int(_pv(p.get("user_cnt")))
                total_profit += _pv(p.get("net_profit"))

            avg_order = total_gmv / total_orders if total_orders > 0 else 0
            business_data["orders"] = {
                "today_count": total_orders,
                "today_gmv": round(total_gmv, 2),
                "avg_order_value": round(avg_order, 2),
                "yesterday_count": 0,
                "yesterday_gmv": 0,
                "growth_rate": 0,
                "net_profit": round(total_profit, 2),
                "customers": total_customers,
            }

        # 热销商品
        hotsale_rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
        )
        if hotsale_rows:
            top_selling = []
            for row in hotsale_rows:
                p = row["payload"]
                if isinstance(p, str):
                    p = json.loads(p)
                name = _sv(p.get("product_name"))
                if not name:
                    continue
                top_selling.append(
                    {
                        "name": name,
                        "category": "",
                        "quantity_sold": int(_pv(p.get("prod_sale_num_gmv"))),
                        "revenue": round(_pv(p.get("prod_sale_amt")), 2),
                        "actual_pay": round(_pv(p.get("prod_actual_pay_amt")), 2),
                        "rank": int(_pv(p.get("rank"))),
                    }
                )
            top_selling.sort(key=lambda x: x["revenue"], reverse=True)
            business_data["products"]["top_selling"] = top_selling[:10]

        # 竞品数据
        try:
            comps = await pool.fetch("""
                SELECT product_name, competitor_name, price
                FROM competitor_products
                WHERE updated_at >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY updated_at DESC LIMIT 20
            """)
            if comps:
                business_data["competitors"]["price_changes"] = [
                    {
                        "product": c["product_name"],
                        "competitor": c["competitor_name"],
                        "price": float(c["price"]),
                    }
                    for c in comps
                ]
        except Exception:
            pass

        # 品类分布
        try:
            cats = await pool.fetch("""
                SELECT category, COUNT(*) as cnt, AVG(retail_price) as avg_price
                FROM products WHERE status = 'active' AND category != ''
                GROUP BY category ORDER BY cnt DESC LIMIT 10
            """)
            business_data["categories"]["performance"] = [
                {
                    "category": c["category"],
                    "product_count": c["cnt"],
                    "avg_price": round(float(c["avg_price"] or 0), 2),
                }
                for c in cats
            ]
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Failed to get business data from dataset_records: {e}")

    # ── Fallback: structured tables for orders/products/trends ──
    orders_snapshot = business_data.get("orders") or {}
    if not orders_snapshot.get("today_count"):
        try:
            metrics_rows = await pool.fetch(
                """
                SELECT metric_date, valid_order_count, valid_order_amount, avg_order_value,
                       net_profit, customer_count
                FROM qnh_daily_metrics
                WHERE channel IS NULL
                ORDER BY metric_date DESC
                LIMIT 2
            """
            )
            if metrics_rows:
                today_metrics = metrics_rows[0]
                prev_metrics = metrics_rows[1] if len(metrics_rows) > 1 else None
                today_orders = int(today_metrics["valid_order_count"] or 0)
                today_revenue = float(today_metrics["valid_order_amount"] or 0)
                avg_order_value = float(today_metrics["avg_order_value"] or 0)
                if not avg_order_value and today_orders > 0:
                    avg_order_value = today_revenue / today_orders
                yesterday_orders = int(prev_metrics["valid_order_count"]) if prev_metrics else 0
                yesterday_revenue = (
                    float(prev_metrics["valid_order_amount"] or 0) if prev_metrics else 0
                )
                growth_rate = (
                    round((today_orders - yesterday_orders) / yesterday_orders * 100, 2)
                    if yesterday_orders > 0
                    else 0
                )
                business_data["orders"] = {
                    "today_count": today_orders,
                    "today_gmv": round(today_revenue, 2),
                    "avg_order_value": round(avg_order_value, 2),
                    "yesterday_count": yesterday_orders,
                    "yesterday_gmv": round(yesterday_revenue, 2),
                    "growth_rate": growth_rate,
                    "net_profit": round(float(today_metrics["net_profit"] or 0), 2),
                    "customers": int(today_metrics["customer_count"] or 0),
                }
        except Exception as e:
            logger.warning("Failed to fallback orders from qnh_daily_metrics: %s", e)

    if not business_data.get("products", {}).get("top_selling"):
        try:
            week_start = today - timedelta(days=7)
            rows = await pool.fetch(
                """
                SELECT sh.product_id,
                       COALESCE(p.name, sh.product_id::text) AS product_name,
                       SUM(sh.quantity)::int AS qty,
                       SUM(sh.revenue) AS revenue
                FROM sales_history sh
                LEFT JOIN products p ON sh.product_id = p.product_id
                WHERE sh.sale_date >= $1
                GROUP BY sh.product_id, product_name
                ORDER BY revenue DESC
                LIMIT 10
            """,
                week_start,
            )
            if rows:
                business_data["products"]["top_selling"] = [
                    {
                        "product_id": row["product_id"],
                        "name": row["product_name"],
                        "quantity_sold": row["qty"],
                        "revenue": round(float(row["revenue"] or 0), 2),
                        "actual_pay": round(float(row["revenue"] or 0), 2),
                        "rank": idx + 1,
                    }
                    for idx, row in enumerate(rows)
                ]
        except Exception as e:
            logger.debug("Fallback top_selling failed: %s", e)

    if not business_data.get("trends", {}).get("weekly"):
        try:
            last_week = today - timedelta(days=7)
            trend_rows = await pool.fetch(
                """
                SELECT metric_date AS date,
                       COALESCE(valid_order_count, 0) AS orders,
                       COALESCE(valid_order_amount, 0) AS gmv
                FROM qnh_daily_metrics
                WHERE channel IS NULL AND metric_date >= $1
                ORDER BY metric_date
            """,
                last_week,
            )
            if trend_rows:
                business_data["trends"]["weekly"] = [
                    {
                        "date": str(row["date"]),
                        "order_count": int(row["orders"]),
                        "gmv": round(float(row["gmv"]), 2),
                    }
                    for row in trend_rows
                ]
        except Exception as e:
            logger.debug("Fallback weekly trend failed: %s", e)

    if not business_data.get("trends", {}).get("weekly"):
        try:
            last_week = today - timedelta(days=7)
            sale_rows = await pool.fetch(
                """
                SELECT sale_date AS date,
                       SUM(quantity)::int AS orders,
                       SUM(revenue) AS gmv
                FROM sales_history
                WHERE sale_date >= $1
                GROUP BY sale_date
                ORDER BY sale_date
            """,
                last_week,
            )
            if sale_rows:
                business_data["trends"]["weekly"] = [
                    {
                        "date": str(row["date"]),
                        "order_count": row["orders"],
                        "gmv": round(float(row["gmv"] or 0), 2),
                    }
                    for row in sale_rows
                ]
        except Exception as e:  # pragma: no cover - fallback logging
            logger.debug("sales_history trend fallback failed: %s", e)

    # ── Fallback: fill in missing data from old tables ──
    if not business_data.get("categories", {}).get("performance"):
        try:
            cats = await pool.fetch("""
                SELECT category, COUNT(*) as cnt FROM qnh_products
                WHERE status = '在售' AND category != ''
                GROUP BY category ORDER BY cnt DESC LIMIT 10
            """)
            business_data["categories"]["performance"] = [
                {"category": c["category"], "product_count": c["cnt"]} for c in cats
            ]
        except Exception:
            business_data["categories"]["performance"] = []

    if not business_data.get("competitors", {}).get("price_changes"):
        business_data["competitors"]["price_changes"] = []

    # 7天趋势 — 从 dataset_records daily snapshots
    try:
        last_week = today - timedelta(days=7)
        trend_rows = await pool.fetch(
            """
            SELECT synced_at::date AS date, payload
            FROM qnh_dataset_records
            WHERE dataset = 'store_rank' AND synced_at >= $1
            ORDER BY synced_at
        """,
            last_week,
        )
        daily_trends: dict[str, dict] = {}
        for row in trend_rows:
            d = str(row["date"])
            p = row["payload"]
            if isinstance(p, str):
                p = json.loads(p)
            if d not in daily_trends:
                daily_trends[d] = {"date": d, "order_count": 0, "gmv": 0.0}
            daily_trends[d]["order_count"] += int(_pv(p.get("eff_ord_cnt")))
            daily_trends[d]["gmv"] += _pv(p.get("sale_amt_gmv"))
        business_data["trends"]["weekly"] = sorted(daily_trends.values(), key=lambda x: x["date"])
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
    你是一位资深的医疗器械即时零售运营专家。分析以下美团即时零售（医疗器械类目）门店数据，生成CEO级别的经营洞察报告。

    ## 今日经营数据
    {json.dumps(business_data, ensure_ascii=False, indent=2)}

    ## 外部因素
    {json.dumps(external_factors, ensure_ascii=False, indent=2)}

    ## 分析要求

    **1. Summary（100-200字）**：用数据说话。包含：今日GMV、订单量、客单价的表现评价（好/差/持平），最值得关注的1-2个数据点，以及与行业平均水平的对比。

    **2. 异常检测**：
    - 哪些商品/品类的销量或价格出现异常波动？具体数字是什么？
    - 缺货商品造成的损失金额估算
    - 超时配送率是否在安全线内（行业标准<5%）

    **3. 具体可执行建议（5条）**：
    每条建议必须包含：具体做什么、预期收益（¥金额或%提升）、执行时间线。
    示例格式："将验孕棒库存从X提升到Y，预计减少¥Z缺货损失/周"
    不要给"关注XX"这种空话，要给"调整XX到YY"这种具体动作。

    **4. 风险预警**：
    - 哪些指标接近危险线？
    - 未来3天可能出现什么问题？

    **5. 增长机会**：
    - 哪些品类有未被满足的需求？
    - 竞品在哪些品类价格偏高，我们可以抢份额？

    医疗器械即时零售特点：
    - 客单价通常¥30-80，高端器械¥200+
    - 即时需求强（验孕、避孕、测温等），配送速度是核心竞争力
    - 毛利率通常25-40%，检测试剂类毛利最高
    - 复购率关键品类：口罩、消毒用品、检测试纸
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
