"""智能日报推送服务 — 每日22:00自动生成经营日报并推送给店主。

融合数据:
  - 门店 KPI 概览 (qnh_store_metrics_raw) — 核心指标汇总+门店排行
  - 热销商品排行 (qnh_products_raw) — Top 10 热销品
  - 消费排行 (qnh_customers_raw) — 高价值客户 Top 10
  - 渠道分布 (qnh_traffic_channels_raw) — 各渠道占比变化
  - 趋势数据 (qnh_traffic_raw) — 趋势图数据
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.db import postgres as pg
from src.services import notification
from src.services.raw_data import fetch_latest_raw

logger = logging.getLogger(__name__)


@dataclass
class DailyReport:
    """日报数据模型"""

    date: str
    # 销售指标
    revenue: float = 0
    order_count: int = 0
    avg_order_value: float = 0
    revenue_vs_yesterday: float = 0  # 百分比变化
    revenue_vs_last_week: float = 0
    order_vs_yesterday: float = 0
    order_vs_last_week: float = 0
    # 热销/滞销
    top_products: list[dict[str, Any]] = field(default_factory=list)
    slow_products: list[dict[str, Any]] = field(default_factory=list)
    # 客服统计
    cs_total: int = 0
    cs_ai_ratio: float = 0
    cs_human_transfer: int = 0
    # 预警摘要
    alerts_triggered: int = 0
    alerts_resolved: int = 0
    alerts_pending: int = 0
    alert_details: list[dict[str, Any]] = field(default_factory=list)
    # 明日待办
    todo_items: list[str] = field(default_factory=list)
    # 低库存商品数（来自 qnh_inventory）
    low_stock_count: int = 0
    # 竞品动态
    competitor_changes: list[dict[str, Any]] = field(default_factory=list)
    # 牵牛花数据 — 核心 KPI、热销商品、消费排行、渠道分布、趋势数据
    store_kpi: dict[str, Any] = field(default_factory=dict)
    store_ranking: list[dict[str, Any]] = field(default_factory=list)
    hotsale_top10: list[dict[str, Any]] = field(default_factory=list)
    customer_top10: list[dict[str, Any]] = field(default_factory=list)
    channel_distribution: list[dict[str, Any]] = field(default_factory=list)
    trend_data: list[dict[str, Any]] = field(default_factory=list)


class DailyReportService:
    """智能日报服务"""

    async def generate_daily_report(self, report_date: date | None = None) -> DailyReport:
        """生成指定日期的经营日报"""
        if report_date is None:
            report_date = date.today()

        pool = pg.get_pool()
        report = DailyReport(date=str(report_date))

        yesterday = report_date - timedelta(days=1)
        last_week = report_date - timedelta(days=7)

        # ── 销售指标 ──
        today_stats = await self._get_day_stats(pool, report_date)
        yesterday_stats = await self._get_day_stats(pool, yesterday)
        last_week_stats = await self._get_day_stats(pool, last_week)

        report.revenue = today_stats["revenue"]
        report.order_count = today_stats["orders"]
        report.avg_order_value = round(report.revenue / max(report.order_count, 1), 2)

        report.revenue_vs_yesterday = self._pct_change(
            today_stats["revenue"], yesterday_stats["revenue"]
        )
        report.revenue_vs_last_week = self._pct_change(
            today_stats["revenue"], last_week_stats["revenue"]
        )
        report.order_vs_yesterday = self._pct_change(
            today_stats["orders"], yesterday_stats["orders"]
        )
        report.order_vs_last_week = self._pct_change(
            today_stats["orders"], last_week_stats["orders"]
        )

        # ── Top 3 热销 + Top 3 滞销 ──
        top_rows = await pool.fetch(
            """SELECT p.product_id, p.name, SUM(oi.quantity)::int AS qty,
                      SUM(oi.unit_price * oi.quantity) AS revenue
               FROM order_items oi
               JOIN products p ON oi.product_id = p.product_id
               JOIN orders o ON oi.order_id = o.order_id
               WHERE o.order_time::date = $1
               GROUP BY p.product_id, p.name
               ORDER BY qty DESC LIMIT 3""",
            report_date,
        )
        report.top_products = [dict(r) for r in top_rows]

        slow_rows = await pool.fetch(
            """SELECT p.product_id, p.name, p.stock,
                      COALESCE(s.qty, 0)::int AS daily_sales
               FROM products p
               LEFT JOIN (
                   SELECT oi.product_id, SUM(oi.quantity) AS qty
                   FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
                   WHERE o.order_time >= $1::timestamp - INTERVAL '7 days' AND o.order_time < $1::timestamp + INTERVAL '1 day'
                   GROUP BY oi.product_id
               ) s ON p.product_id = s.product_id
               WHERE p.status = 'active'
               ORDER BY COALESCE(s.qty, 0) ASC LIMIT 3""",
            report_date,
        )
        report.slow_products = [dict(r) for r in slow_rows]

        # ── 客服统计 ──
        cs_row = await pool.fetchrow("SELECT * FROM cs_analytics WHERE date = $1", report_date)
        if cs_row:
            report.cs_total = cs_row["total_inquiries"]
            report.cs_ai_ratio = round(cs_row["ai_handled"] / max(cs_row["total_inquiries"], 1), 2)
            report.cs_human_transfer = cs_row["human_transfer"]
        else:
            # Fallback: count from sessions
            cs_count = (
                await pool.fetchval(
                    "SELECT COUNT(*)::int FROM cs_sessions WHERE created_at::date = $1",
                    report_date,
                )
                or 0
            )
            report.cs_total = cs_count

        # ── 预警摘要 ──
        alert_rows = await pool.fetch(
            """SELECT alert_type, severity, status, message
               FROM alerts WHERE created_at::date = $1
               ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END
               LIMIT 10""",
            report_date,
        )
        report.alerts_triggered = len(alert_rows)
        report.alerts_resolved = sum(1 for r in alert_rows if r["status"] == "resolved")
        report.alerts_pending = sum(1 for r in alert_rows if r["status"] == "pending")
        report.alert_details = [dict(r) for r in alert_rows[:5]]

        # ── 牵牛花原始数据融合 ──
        await self._enrich_from_raw_tables(pool, report)

        # ── 明日待办（AI生成） ──
        report.todo_items = await self._generate_todo(pool, report_date, report)

        # ── 竞品动态 ──
        try:
            comp_rows = await pool.fetch(
                """SELECT name, price, monthly_sales
                   FROM competitor_products
                   WHERE last_synced::date = $1
                   ORDER BY monthly_sales DESC LIMIT 5""",
                report_date,
            )
            report.competitor_changes = [dict(r) for r in comp_rows]
        except Exception as e:
            logger.debug(f"competitor_products not available for daily report (graceful): {e}")
            report.competitor_changes = []

        # ── 从 qnh 结构化表补充/覆盖关键数据 ──
        await self._enrich_from_qnh_structured(pool, report, report_date)

        return report

    async def push_report(self, report: DailyReport) -> bool:
        """生成 markdown 日报并通过 notification.send_report() 多渠道推送"""
        title = f"【AI店长日报】{report.date}"
        body = self._build_markdown_body(report)

        result = await notification.send_report(title, body)
        sent = result.get("sent", False)
        logger.info(
            "Daily report push result: sent=%s channels=%s",
            sent,
            result.get("channels_sent"),
        )
        return sent

    def _build_markdown_body(self, report: DailyReport) -> str:
        """构建 markdown 格式日报正文（兼容飞书/微信/钉钉 markdown）"""

        def trend(pct: float) -> str:
            if pct > 0:
                return f"📈 +{pct:.1f}%"
            elif pct < 0:
                return f"📉 {pct:.1f}%"
            return "→ 持平"

        lines: list[str] = []

        # ── 销售概览 ──
        lines += [
            "## 💰 销售概览",
            f"- **销售额**: ¥{report.revenue:,.0f}  {trend(report.revenue_vs_yesterday)} vs昨日  {trend(report.revenue_vs_last_week)} vs上周",
            f"- **订单数**: {report.order_count}  {trend(report.order_vs_yesterday)} vs昨日",
            f"- **客单价**: ¥{report.avg_order_value:.0f}",
        ]

        # ── 低库存 ──
        if report.low_stock_count:
            lines.append(f"- **低库存商品**: {report.low_stock_count} 个")

        # ── 热销 Top 5（qnh_orders 数据优先） ──
        if report.top_products:
            lines += ["", "## 🔥 热销商品 Top 5"]
            for i, p in enumerate(report.top_products[:5], 1):
                name = p.get("name") or p.get("productName", "未知")
                qty = p.get("qty") or p.get("salesCount") or p.get("saleCount", "")
                rev = p.get("revenue") or p.get("salesAmount") or p.get("saleAmount", "")
                rev_str = f"  ¥{float(rev):,.0f}" if rev != "" else ""
                lines.append(f"{i}. **{name}**  销量 {qty}{rev_str}")

        # ── 牵牛花核心 KPI ──
        if report.store_kpi:
            kpi = report.store_kpi
            lines += ["", "## 📊 核心 KPI（牵牛花）"]
            for label, key in [
                ("有效订单金额", "validOrderAmount"),
                ("有效订单数", "validOrderCount"),
                ("客单价", "customerPrice"),
                ("配送费", "deliveryFee"),
            ]:
                val = kpi.get(key, kpi.get(label))
                if val is not None:
                    lines.append(f"- **{label}**: {val}")

        # ── 牵牛花热销 Top 10 ──
        if report.hotsale_top10:
            lines += ["", "## 🏆 热销商品 Top 10（牵牛花）"]
            for i, p in enumerate(report.hotsale_top10, 1):
                name = p.get("productName", p.get("name", "未知"))
                sales = p.get("salesAmount", p.get("saleAmount", ""))
                qty = p.get("salesCount", p.get("saleCount", ""))
                lines.append(f"{i}. {name}  销额 {sales}  销量 {qty}")

        # ── 高价值客户 Top 5 ──
        if report.customer_top10:
            lines += ["", "## 👑 高价值客户 Top 5"]
            for i, c in enumerate(report.customer_top10[:5], 1):
                name = c.get("customerName", c.get("nickname", "匿名"))
                amount = c.get("consumeAmount", c.get("totalAmount", ""))
                lines.append(f"{i}. {name}  消费 {amount}")

        # ── 渠道分布 ──
        if report.channel_distribution:
            lines += ["", "## 📡 渠道分布"]
            for ch in report.channel_distribution:
                name = ch.get("channelName", ch.get("channel", "未知"))
                ratio = ch.get("orderRatio", ch.get("ratio", ""))
                lines.append(f"- {name}: {ratio}")

        # ── 客服统计 ──
        lines += [
            "",
            "## 💬 客服统计",
            f"- 咨询 {report.cs_total} 次  AI处理 {report.cs_ai_ratio:.0%}  转人工 {report.cs_human_transfer}",
        ]

        # ── 预警摘要 ──
        if report.alerts_triggered:
            lines += [
                "",
                "## 🔔 今日预警",
                f"- 触发 **{report.alerts_triggered}**  待处理 **{report.alerts_pending}**  已解决 {report.alerts_resolved}",
            ]
            for a in report.alert_details[:3]:
                sev = a.get("severity", "")
                msg = a.get("message", a.get("root_cause", ""))
                lines.append(f"  - [{sev}] {msg}")

        # ── 明日待办 ──
        if report.todo_items:
            lines += ["", "## 📋 明日待办"]
            for item in report.todo_items:
                lines.append(f"- {item}")

        lines += ["", f"> ⏰ {datetime.now().strftime('%H:%M')} 自动生成"]

        return "\n".join(lines)

    # ── 私有方法 ──

    async def _enrich_from_qnh_structured(
        self, pool, report: DailyReport, report_date: date
    ) -> None:
        """从牵牛花结构化表（qnh_daily_metrics / qnh_orders / qnh_inventory）读取数据。

        若表不存在或字段不匹配，静默降级，不影响已有数据。
        """
        # 1. qnh_daily_metrics — GMV、订单数、客单价（覆盖 orders 表汇总值）
        try:
            row = await pool.fetchrow(
                "SELECT * FROM qnh_daily_metrics WHERE date::date = $1 LIMIT 1",
                report_date,
            )
            if row:
                d = dict(row)
                gmv = d.get("gmv") or d.get("total_amount") or d.get("revenue") or d.get("valid_order_amount")
                cnt = d.get("order_count") or d.get("valid_order_count") or d.get("orders")
                aov = d.get("avg_order_value") or d.get("customer_price")
                if gmv is not None:
                    report.revenue = float(gmv)
                if cnt is not None:
                    report.order_count = int(cnt)
                if aov is not None:
                    report.avg_order_value = float(aov)
                elif report.order_count > 0:
                    report.avg_order_value = round(report.revenue / report.order_count, 2)
                logger.debug("Enriched KPI from qnh_daily_metrics for %s", report_date)
        except Exception as e:
            logger.debug("qnh_daily_metrics not available: %s", e)

        # 2. qnh_orders — Top 5 热销商品（覆盖 order_items 聚合结果）
        try:
            rows = await pool.fetch(
                """
                SELECT
                    COALESCE(product_id, '') AS product_id,
                    COALESCE(product_name, name, '') AS name,
                    SUM(COALESCE(quantity, qty, 1))::int AS qty,
                    SUM(COALESCE(amount, price, 0)) AS revenue
                FROM qnh_orders
                WHERE (order_date::date = $1 OR created_at::date = $1)
                GROUP BY product_id, product_name, name
                ORDER BY qty DESC
                LIMIT 5
                """,
                report_date,
            )
            if rows:
                report.top_products = [dict(r) for r in rows]
                logger.debug("Enriched top_products from qnh_orders for %s", report_date)
        except Exception as e:
            logger.debug("qnh_orders not available: %s", e)

        # 3. qnh_inventory — 低库存商品数
        try:
            count = await pool.fetchval(
                """
                SELECT COUNT(*)::int FROM qnh_inventory
                WHERE COALESCE(stock, quantity, 0) < COALESCE(safety_stock, min_stock, 10)
                """
            )
            if count is not None:
                report.low_stock_count = int(count)
                logger.debug("Enriched low_stock_count=%d from qnh_inventory", report.low_stock_count)
        except Exception as e:
            logger.debug("qnh_inventory not available: %s", e)

        # 4. alerts — 今日新增预警数（补充到 alerts_triggered，已有则取较大值）
        try:
            today_alert_count = await pool.fetchval(
                "SELECT COUNT(*)::int FROM alerts WHERE created_at::date = $1",
                report_date,
            )
            if today_alert_count is not None and today_alert_count > report.alerts_triggered:
                report.alerts_triggered = int(today_alert_count)
        except Exception as e:
            logger.debug("alerts count query failed: %s", e)

    async def _enrich_from_raw_tables(self, pool, report: DailyReport) -> None:
        """从牵牛花 raw 表读取数据，填充日报的扩展字段。"""
        # 1. 门店 KPI 概览（来自 qnh_store_metrics_raw）
        metrics = await fetch_latest_raw(pool, "qnh_store_metrics_raw")
        if metrics:
            if isinstance(metrics, list):
                # 多门店: 第一条当汇总，全部作为门店排行
                report.store_kpi = metrics[0] if metrics else {}
                report.store_ranking = metrics
            else:
                report.store_kpi = metrics

        # 2. 热销商品 Top 10（来自 qnh_products_raw）
        products = await fetch_latest_raw(pool, "qnh_products_raw")
        if products:
            items = products if isinstance(products, list) else [products]
            report.hotsale_top10 = items[:10]

        # 3. 消费排行 Top 10（来自 qnh_customers_raw）
        customers = await fetch_latest_raw(pool, "qnh_customers_raw")
        if customers:
            items = customers if isinstance(customers, list) else [customers]
            report.customer_top10 = items[:10]

        # 4. 渠道分布（来自 qnh_traffic_channels_raw）
        channels = await fetch_latest_raw(pool, "qnh_traffic_channels_raw")
        if channels:
            report.channel_distribution = channels if isinstance(channels, list) else [channels]

        # 5. 趋势数据（来自 qnh_traffic_raw，可供前端画趋势图）
        trend = await fetch_latest_raw(pool, "qnh_traffic_raw")
        if trend:
            report.trend_data = trend if isinstance(trend, list) else [trend]

    async def _get_day_stats(self, pool, d: date) -> dict:
        row = await pool.fetchrow(
            """SELECT COALESCE(SUM(total_amount), 0) AS revenue,
                      COUNT(*)::int AS orders
               FROM orders WHERE order_time::date = $1""",
            d,
        )
        return {"revenue": float(row["revenue"]), "orders": row["orders"]}

    def _pct_change(self, current: float, previous: float) -> float:
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round((current - previous) / previous * 100, 1)

    async def _generate_todo(self, pool, report_date: date, report: DailyReport) -> list[str]:
        """基于数据生成明日待办"""
        todos = []

        # 库存低于安全线的商品
        low_stock = await pool.fetch(
            """SELECT name, stock FROM products
               WHERE status = 'active' AND stock < 10
               ORDER BY stock ASC LIMIT 3"""
        )
        for r in low_stock:
            todos.append(f"补货: {r['name']}（库存仅{r['stock']}）")

        # 待处理预警
        if report.alerts_pending > 0:
            todos.append(f"处理 {report.alerts_pending} 条待处理预警")

        # 滞销商品促销建议
        if report.slow_products:
            name = report.slow_products[0].get("name", "")
            if name:
                todos.append(f"考虑对「{name}」做促销或调价")

        if not todos:
            todos.append("✅ 运营数据正常，保持现有策略")

        return todos
