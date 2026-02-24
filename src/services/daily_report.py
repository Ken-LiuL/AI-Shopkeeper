"""智能日报推送服务 — 每日22:00自动生成经营日报并推送给店主。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.db import postgres as pg
from src.skills.notifier import NotifierSkill

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
    # 竞品动态
    competitor_changes: list[dict[str, Any]] = field(default_factory=list)


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
                   WHERE o.order_time >= $1 - INTERVAL '7 days' AND o.order_time < $1 + INTERVAL '1 day'
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

        # ── 明日待办（AI生成） ──
        report.todo_items = await self._generate_todo(pool, report_date, report)

        # ── 竞品动态 ──
        comp_rows = await pool.fetch(
            """SELECT name, price, monthly_sales
               FROM competitor_products
               WHERE last_synced::date = $1
               ORDER BY monthly_sales DESC LIMIT 5""",
            report_date,
        )
        report.competitor_changes = [dict(r) for r in comp_rows]

        return report

    async def push_report(self, report: DailyReport) -> bool:
        """通过企业微信推送日报"""
        webhook_url = os.environ.get("WECHAT_WEBHOOK_URL", "")
        notifier = NotifierSkill(webhook_url=webhook_url)

        # 构建推送消息
        arrow_up = "📈"
        arrow_down = "📉"

        def trend(pct: float) -> str:
            if pct > 0:
                return f"{arrow_up}+{pct:.1f}%"
            elif pct < 0:
                return f"{arrow_down}{pct:.1f}%"
            return "→ 持平"

        lines = [
            f"📊 【AI店长日报】{report.date}",
            "",
            "💰 销售概览:",
            f"  • 销售额: ¥{report.revenue:,.0f}  {trend(report.revenue_vs_yesterday)} vs昨日  {trend(report.revenue_vs_last_week)} vs上周",
            f"  • 订单数: {report.order_count}  {trend(report.order_vs_yesterday)} vs昨日",
            f"  • 客单价: ¥{report.avg_order_value:.0f}",
        ]

        if report.top_products:
            lines.append("")
            lines.append("🔥 热销 Top 3:")
            for i, p in enumerate(report.top_products, 1):
                lines.append(f"  {i}. {p['name']}  销量{p['qty']}  ¥{p.get('revenue', 0):,.0f}")

        if report.slow_products:
            lines.append("")
            lines.append("🐌 滞销 Top 3:")
            for i, p in enumerate(report.slow_products, 1):
                lines.append(
                    f"  {i}. {p['name']}  库存{p.get('stock', 0)}  7日仅售{p.get('daily_sales', 0)}"
                )

        lines.append("")
        lines.append(
            f"💬 客服: 咨询{report.cs_total}次  AI处理{report.cs_ai_ratio:.0%}  转人工{report.cs_human_transfer}"
        )

        if report.alerts_triggered:
            lines.append(
                f"🔔 预警: 触发{report.alerts_triggered}  待处理{report.alerts_pending}  已解决{report.alerts_resolved}"
            )

        if report.todo_items:
            lines.append("")
            lines.append("📋 明日待办:")
            for item in report.todo_items:
                lines.append(f"  • {item}")

        lines.append(f"\n⏰ {datetime.now().strftime('%H:%M')} 自动生成")

        return await notifier.send_text("\n".join(lines))

    # ── 私有方法 ──

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
