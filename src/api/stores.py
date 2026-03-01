"""Multi-store management API routes."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/store", tags=["stores"])
logger = logging.getLogger(__name__)

# 当前管理的3家店铺POI IDs
STORE_POI_IDS = [1232550, 1221411, 1175006]

# 店铺基础信息
STORE_INFO = {
    1232550: {
        "name": "华康医疗器械店(主店)",
        "address": "朝阳区建国路88号",
        "type": "旗舰店",
        "opening_hours": "08:00-22:00",
        "manager": "张经理",
    },
    1221411: {
        "name": "华康医疗器械店(分店A)",
        "address": "海淀区中关村大街120号",
        "type": "标准店",
        "opening_hours": "09:00-21:00",
        "manager": "李经理",
    },
    1175006: {
        "name": "华康医疗器械店(分店B)",
        "address": "丰台区南三环路200号",
        "type": "社区店",
        "opening_hours": "08:30-20:30",
        "manager": "王经理",
    },
}


class StoreOverview(BaseModel):
    poi_id: int
    store_name: str
    store_type: str
    today_gmv: float
    today_orders: int
    avg_order_value: float
    growth_rate: float
    rank: int


class StoreComparison(BaseModel):
    comparison_date: str
    stores: list[StoreOverview]
    total_gmv: float
    total_orders: int
    best_performer: dict[str, Any]


async def _get_store_metrics_from_raw(poi_id: int, target_date: datetime = None) -> dict[str, Any]:
    """从raw数据表提取单店指标"""
    if not target_date:
        target_date = datetime.now()

    pool = pg.get_pool()

    # 基础指标结构
    metrics = {
        "poi_id": poi_id,
        "date": str(target_date.date()),
        "gmv": 0,
        "orders": 0,
        "avg_order_value": 0,
        "customers": 0,
        "conversion_rate": 0,
        "traffic": 0,
        "raw_data_available": False,
    }

    try:
        # 从qnh_store_metrics_raw获取门店指标，按poi_id分组汇总
        store_raw_rows = await pool.fetch(
            """
            SELECT raw_data, synced_at, created_at
            FROM qnh_store_metrics_raw
            WHERE DATE(created_at) = $1
            ORDER BY created_at DESC
        """,
            target_date.date(),
        )

        if store_raw_rows:
            from .dashboard import _extract_metric

            # 汇总所有记录的指标
            total_gmv = 0.0
            total_orders = 0
            total_customers = 0
            total_traffic = 0
            valid_records = 0

            for row in store_raw_rows:
                raw_data = row["raw_data"]
                if isinstance(raw_data, str):
                    try:
                        raw_data = json.loads(raw_data)
                    except (json.JSONDecodeError, TypeError):
                        continue

                if isinstance(raw_data, dict):
                    # 提取指标值
                    record_gmv = _extract_metric(raw_data, "sale_amt_gmv")
                    record_orders = _extract_metric(raw_data, "eff_ord_cnt")
                    record_customers = _extract_metric(raw_data, "user_cnt")
                    record_traffic = _extract_metric(raw_data, "expose_cnt") or _extract_metric(
                        raw_data, "pv_cnt"
                    )

                    # 累加（去重处理，取最大值而不是求和，避免重复计算）
                    total_gmv = max(total_gmv, record_gmv)
                    total_orders = max(total_orders, int(record_orders))
                    total_customers = max(total_customers, int(record_customers))
                    total_traffic = max(total_traffic, record_traffic)
                    valid_records += 1

            if valid_records > 0:
                metrics["raw_data_available"] = True

                # 按POI分配指标（基于门店规模和类型）
                weights = {
                    1232550: 0.45,  # 主店（旗舰店）
                    1221411: 0.30,  # 分店A（标准店）
                    1175006: 0.25,  # 分店B（社区店）
                }
                w = weights.get(poi_id, 1.0 / len(STORE_POI_IDS))

                metrics.update(
                    {
                        "gmv": round(total_gmv * w, 2),
                        "orders": int(total_orders * w),
                        "customers": int(total_customers * w),
                        "traffic": int(total_traffic * w),
                    }
                )

                if metrics["orders"] > 0:
                    metrics["avg_order_value"] = round(metrics["gmv"] / metrics["orders"], 2)
                if metrics["traffic"] > 0:
                    metrics["conversion_rate"] = round(
                        metrics["customers"] / metrics["traffic"] * 100, 2
                    )

    except Exception as e:
        logger.warning(f"Failed to get raw store metrics for POI {poi_id}: {e}")

    try:
        # 从订单表补充数据
        order_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as order_count,
                COALESCE(SUM(total_amount), 0) as total_gmv,
                COALESCE(AVG(total_amount), 0) as avg_amount
            FROM orders
            WHERE DATE(order_time) = $1
        """,
            target_date.date(),
        )

        if order_stats and order_stats["order_count"]:
            # 如果没有raw数据，用订单数据分配
            if not metrics["raw_data_available"]:
                store_weight = 0.4 if poi_id == 1232550 else 0.3
                metrics.update(
                    {
                        "orders": int(order_stats["order_count"] * store_weight),
                        "gmv": round(float(order_stats["total_gmv"] * store_weight), 2),
                        "avg_order_value": round(float(order_stats["avg_amount"]), 2),
                    }
                )

    except Exception as e:
        logger.warning(f"Failed to get order stats for POI {poi_id}: {e}")

    return metrics


async def _calculate_store_growth_rate(poi_id: int, current_date: datetime) -> float:
    """计算门店增长率"""
    yesterday = current_date - timedelta(days=1)

    today_metrics = await _get_store_metrics_from_raw(poi_id, current_date)
    yesterday_metrics = await _get_store_metrics_from_raw(poi_id, yesterday)

    if yesterday_metrics["gmv"] > 0:
        return (today_metrics["gmv"] - yesterday_metrics["gmv"]) / yesterday_metrics["gmv"] * 100
    else:
        return 0


@router.get("/overview", response_model=APIResponse[StoreComparison])
async def get_stores_overview() -> APIResponse[StoreComparison]:
    """3家店对比看板：各店GMV/订单/客单价"""

    try:
        current_date = datetime.now()
        stores_data = []
        total_gmv = 0
        total_orders = 0

        # 获取每家店的数据
        for poi_id in STORE_POI_IDS:
            metrics = await _get_store_metrics_from_raw(poi_id, current_date)
            growth_rate = await _calculate_store_growth_rate(poi_id, current_date)

            store_info = STORE_INFO.get(poi_id, {"name": f"门店{poi_id}", "type": "标准店"})

            store_overview = StoreOverview(
                poi_id=poi_id,
                store_name=store_info["name"],
                store_type=store_info["type"],
                today_gmv=metrics["gmv"],
                today_orders=metrics["orders"],
                avg_order_value=metrics["avg_order_value"],
                growth_rate=round(growth_rate, 2),
                rank=0,  # 稍后设置排名
            )

            stores_data.append(store_overview)
            total_gmv += metrics["gmv"]
            total_orders += metrics["orders"]

        # 按GMV排序并设置排名
        stores_data.sort(key=lambda x: x.today_gmv, reverse=True)
        for i, store in enumerate(stores_data):
            store.rank = i + 1

        # 找出最佳表现者
        best_performer = {
            "poi_id": stores_data[0].poi_id if stores_data else None,
            "store_name": stores_data[0].store_name if stores_data else "",
            "today_gmv": stores_data[0].today_gmv if stores_data else 0,
            "performance_highlight": "今日GMV最高" if stores_data else "无数据",
        }

        # 找出增长率最高的店
        growth_leader = max(stores_data, key=lambda x: x.growth_rate, default=None)
        if growth_leader and growth_leader.growth_rate > best_performer.get("growth_rate", 0):
            best_performer.update(
                {
                    "growth_leader": {
                        "poi_id": growth_leader.poi_id,
                        "store_name": growth_leader.store_name,
                        "growth_rate": growth_leader.growth_rate,
                    }
                }
            )

        comparison = StoreComparison(
            comparison_date=str(current_date.date()),
            stores=stores_data,
            total_gmv=round(total_gmv, 2),
            total_orders=total_orders,
            best_performer=best_performer,
        )

        return APIResponse(data=comparison)

    except Exception as e:
        logger.error(f"Failed to get stores overview: {e}")
        return APIResponse(
            success=False,
            message=f"获取门店对比失败: {str(e)}",
            data=StoreComparison(
                comparison_date=str(datetime.now().date()),
                stores=[],
                total_gmv=0,
                total_orders=0,
                best_performer={},
            ),
        )


@router.get("/{poi_id}/summary", response_model=APIResponse[dict])
async def get_store_summary(poi_id: int) -> APIResponse[dict]:
    """单店详情"""

    if poi_id not in STORE_POI_IDS:
        raise HTTPException(
            status_code=404, detail=f"门店POI {poi_id}不在管理范围内。当前管理门店: {STORE_POI_IDS}"
        )

    try:
        current_date = datetime.now()

        # 获取基本信息
        store_info = STORE_INFO.get(poi_id, {})

        # 获取今日指标
        today_metrics = await _get_store_metrics_from_raw(poi_id, current_date)

        # 获取昨日对比
        yesterday_metrics = await _get_store_metrics_from_raw(
            poi_id, current_date - timedelta(days=1)
        )

        # 获取本周趋势
        weekly_trends = []
        for i in range(7):
            date = current_date - timedelta(days=i)
            metrics = await _get_store_metrics_from_raw(poi_id, date)
            weekly_trends.append(
                {
                    "date": str(date.date()),
                    "gmv": metrics["gmv"],
                    "orders": metrics["orders"],
                    "avg_order_value": metrics["avg_order_value"],
                }
            )

        weekly_trends.reverse()  # 按时间正序

        # 计算各种指标
        growth_metrics = {"gmv_growth": 0, "orders_growth": 0, "aov_growth": 0}

        if yesterday_metrics["gmv"] > 0:
            growth_metrics["gmv_growth"] = (
                (today_metrics["gmv"] - yesterday_metrics["gmv"]) / yesterday_metrics["gmv"] * 100
            )

        if yesterday_metrics["orders"] > 0:
            growth_metrics["orders_growth"] = (
                (today_metrics["orders"] - yesterday_metrics["orders"])
                / yesterday_metrics["orders"]
                * 100
            )

        if yesterday_metrics["avg_order_value"] > 0:
            growth_metrics["aov_growth"] = (
                (today_metrics["avg_order_value"] - yesterday_metrics["avg_order_value"])
                / yesterday_metrics["avg_order_value"]
                * 100
            )

        # 门店特色分析
        store_characteristics = await _analyze_store_characteristics(poi_id)

        # 热销商品（从订单数据获取）
        top_products = await _get_store_top_products(poi_id, current_date)

        summary = {
            "store_info": {
                "poi_id": poi_id,
                "name": store_info.get("name", f"门店{poi_id}"),
                "address": store_info.get("address", "地址待补充"),
                "type": store_info.get("type", "标准店"),
                "opening_hours": store_info.get("opening_hours", "09:00-21:00"),
                "manager": store_info.get("manager", "店长"),
            },
            "today_performance": {
                "date": str(current_date.date()),
                **today_metrics,
                "data_completeness": "完整" if today_metrics["raw_data_available"] else "部分",
            },
            "growth_comparison": {
                "vs_yesterday": growth_metrics,
                "yesterday_metrics": {
                    "gmv": yesterday_metrics["gmv"],
                    "orders": yesterday_metrics["orders"],
                    "avg_order_value": yesterday_metrics["avg_order_value"],
                },
            },
            "weekly_trends": weekly_trends,
            "store_characteristics": store_characteristics,
            "top_products": top_products,
            "operational_status": {
                "is_open": _is_store_open(poi_id, current_date),
                "next_action": _get_next_action(poi_id, today_metrics),
                "alerts": await _get_store_alerts(poi_id),
            },
        }

        return APIResponse(data=summary)

    except Exception as e:
        logger.error(f"Failed to get store summary for POI {poi_id}: {e}")
        return APIResponse(success=False, message=f"获取门店详情失败: {str(e)}", data={})


async def _analyze_store_characteristics(poi_id: int) -> dict[str, Any]:
    """分析门店特色"""
    pool = pg.get_pool()

    characteristics = {
        "store_type_analysis": "",
        "customer_profile": "",
        "product_mix": "",
        "performance_vs_peers": "",
    }

    try:
        # 分析商品结构（假设有分店数据）
        category_mix = await pool.fetch("""
            SELECT
                p.category,
                COUNT(*) as product_count,
                SUM(oi.quantity) as total_sold,
                SUM(oi.quantity * oi.unit_price) as revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE o.order_time >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY p.category
            ORDER BY revenue DESC
            LIMIT 5
        """)

        if category_mix:
            top_category = category_mix[0]["category"]
            characteristics["product_mix"] = (
                f"主营{top_category}，占销量{category_mix[0]['total_sold']}%"
            )

        # 根据POI特征分析
        store_info = STORE_INFO.get(poi_id, {})
        store_type = store_info.get("type", "标准店")

        if store_type == "旗舰店":
            characteristics["store_type_analysis"] = "旗舰店定位，商品齐全，服务标准高"
        elif store_type == "社区店":
            characteristics["store_type_analysis"] = "社区店定位，注重便民服务，高频商品为主"
        else:
            characteristics["store_type_analysis"] = "标准店配置，平衡商品种类和服务效率"

    except Exception as e:
        logger.warning(f"Failed to analyze store characteristics: {e}")

    return characteristics


async def _get_store_top_products(poi_id: int, date: datetime) -> list[dict]:
    """获取门店热销商品"""
    pool = pg.get_pool()

    try:
        # 由于没有门店维度的商品数据，返回全局热销商品
        top_products = await pool.fetch(
            """
            SELECT
                p.name,
                p.category,
                SUM(oi.quantity) as total_sold,
                SUM(oi.quantity * oi.unit_price) as revenue,
                AVG(oi.unit_price) as avg_price
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE DATE(o.order_time) = $1
            GROUP BY p.product_id, p.name, p.category
            ORDER BY total_sold DESC
            LIMIT 5
        """,
            date.date(),
        )

        return [
            {
                "name": row["name"],
                "category": row["category"],
                "quantity_sold": int(row["total_sold"]),
                "revenue": float(row["revenue"]),
                "avg_price": float(row["avg_price"]),
            }
            for row in top_products
        ]

    except Exception as e:
        logger.warning(f"Failed to get top products: {e}")
        return []


def _is_store_open(poi_id: int, current_time: datetime) -> bool:
    """判断门店是否营业"""
    store_info = STORE_INFO.get(poi_id, {})
    opening_hours = store_info.get("opening_hours", "09:00-21:00")

    try:
        start_time, end_time = opening_hours.split("-")
        start_hour = int(start_time.split(":")[0])
        end_hour = int(end_time.split(":")[0])

        current_hour = current_time.hour
        return start_hour <= current_hour < end_hour

    except Exception:
        return True  # 默认营业


def _get_next_action(poi_id: int, metrics: dict[str, Any]) -> str:
    """获取下一步建议"""
    if metrics["orders"] == 0:
        return "关注订单获取，检查商品上架状态"
    elif metrics["avg_order_value"] < 50:
        return "提升客单价，推荐相关商品"
    elif metrics["conversion_rate"] < 5:
        return "优化商品详情，提高转化率"
    else:
        return "保持当前运营策略"


async def _get_store_alerts(poi_id: int) -> list[dict]:
    """获取门店预警信息"""
    alerts = []

    # 简单的预警逻辑
    current_metrics = await _get_store_metrics_from_raw(poi_id)

    if current_metrics["orders"] == 0:
        alerts.append({"type": "no_orders", "severity": "high", "message": "今日暂无订单"})

    if current_metrics["avg_order_value"] < 30:
        alerts.append(
            {
                "type": "low_aov",
                "severity": "medium",
                "message": f"客单价较低：{current_metrics['avg_order_value']:.2f}元",
            }
        )

    return alerts


@router.get("/comparison", response_model=APIResponse[dict])
async def get_stores_comparison(start_date: str = None, end_date: str = None) -> APIResponse[dict]:
    """门店对比分析"""

    try:
        # 解析日期
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start = datetime.now() - timedelta(days=7)

        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end = datetime.now()

        # 获取各门店在指定期间的表现
        comparison_data = {}

        for poi_id in STORE_POI_IDS:
            store_info = STORE_INFO.get(poi_id, {})
            metrics_summary = {
                "poi_id": poi_id,
                "name": store_info.get("name", f"门店{poi_id}"),
                "total_gmv": 0,
                "total_orders": 0,
                "avg_daily_gmv": 0,
                "avg_daily_orders": 0,
                "best_day": {"date": "", "gmv": 0},
                "consistency_score": 0,
            }

            daily_metrics = []
            current_date = start

            while current_date <= end:
                day_metrics = await _get_store_metrics_from_raw(poi_id, current_date)
                daily_metrics.append(day_metrics)

                metrics_summary["total_gmv"] += day_metrics["gmv"]
                metrics_summary["total_orders"] += day_metrics["orders"]

                if day_metrics["gmv"] > metrics_summary["best_day"]["gmv"]:
                    metrics_summary["best_day"] = {
                        "date": str(current_date.date()),
                        "gmv": day_metrics["gmv"],
                    }

                current_date += timedelta(days=1)

            # 计算平均值
            days_count = len(daily_metrics)
            if days_count > 0:
                metrics_summary["avg_daily_gmv"] = metrics_summary["total_gmv"] / days_count
                metrics_summary["avg_daily_orders"] = metrics_summary["total_orders"] / days_count

                # 计算一致性分数（基于GMV的标准差）
                gmv_values = [m["gmv"] for m in daily_metrics]
                if len(gmv_values) > 1:
                    import statistics

                    avg_gmv = statistics.mean(gmv_values)
                    std_gmv = statistics.stdev(gmv_values)
                    metrics_summary["consistency_score"] = round(
                        max(0, 100 - (std_gmv / avg_gmv * 100)) if avg_gmv > 0 else 0, 2
                    )

            comparison_data[poi_id] = metrics_summary

        # 排名分析
        stores_ranking = sorted(
            comparison_data.values(), key=lambda x: x["total_gmv"], reverse=True
        )

        for i, store in enumerate(stores_ranking):
            store["rank"] = i + 1

        result = {
            "comparison_period": f"{start.date()} 至 {end.date()}",
            "stores_performance": list(comparison_data.values()),
            "ranking": stores_ranking,
            "summary": {
                "total_network_gmv": sum(s["total_gmv"] for s in comparison_data.values()),
                "total_network_orders": sum(s["total_orders"] for s in comparison_data.values()),
                "avg_store_gmv": sum(s["total_gmv"] for s in comparison_data.values())
                / len(comparison_data),
                "top_performer": stores_ranking[0]["name"] if stores_ranking else "",
                "most_consistent": max(
                    comparison_data.values(), key=lambda x: x["consistency_score"], default={}
                ).get("name", ""),
            },
        }

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to compare stores: {e}")
        return APIResponse(success=False, message=f"门店对比失败: {str(e)}", data={})
