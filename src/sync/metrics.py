"""Metrics Syncer — daily business metrics via goldengateway."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class MetricsSyncer(BaseSyncer):
    """Sync daily business metrics from QNH via goldengateway.

    Data source: #/data/home/new
    API: POST /goldengateway/empower/generic/table/query (module=storeDetail)
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "metrics"
    full_sync_interval = timedelta(hours=20)

    # 推断的 module 名，需验证
    MODULE_STORE_DETAIL = "storeDetail"

    async def full_sync(self) -> SyncResult:
        """Full sync: last 30 days of daily metrics."""
        end = datetime.now(CST).date()
        start = end - timedelta(days=30)
        return await self._sync_date_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental: metrics since last sync (usually yesterday)."""
        end = datetime.now(CST).date()
        start = since.date() if isinstance(since, datetime) else since
        return await self._sync_date_range(start, end, SyncMode.INCREMENTAL)

    async def _sync_date_range(self, start: Any, end: Any, mode: SyncMode) -> SyncResult:
        total = 0
        from datetime import date as date_cls

        current = start if isinstance(start, date_cls) else start.date()
        end_date = end if isinstance(end, date_cls) else end.date()

        try:
            while current <= end_date:
                date_str = current.strftime("%Y-%m-%d")

                # 使用 goldengateway 通用查询接口查门店指标
                # NOTE: module 和参数格式为推断，需抓包验证
                try:
                    resp = await self.client.golden_query(
                        module=self.MODULE_STORE_DETAIL,
                        start_date=date_str,
                        end_date=date_str,
                    )
                    data = resp.get("data", {})
                    # goldengateway 可能返回 table rows 或嵌套结构
                    rows = data.get("list", data.get("rows", data.get("records", [])))
                    if rows:
                        for row in rows:
                            channel = row.get("channel", row.get("channelName"))
                            await self._upsert_metrics(current, channel, row)
                            total += 1
                    elif data:
                        # 可能直接返回汇总数据
                        await self._upsert_metrics(current, None, data)
                        total += 1
                except Exception as e:
                    self.logger.warning(f"Failed to fetch metrics for {date_str}: {e}")

                current += timedelta(days=1)

            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=True,
                records_synced=total,
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=False,
                records_synced=total,
                error=str(e),
            )

    async def _upsert_metrics(
        self, metric_date: Any, channel: str | None, data: dict[str, Any]
    ) -> None:
        if not self.pool:
            return

        # Extract channel distribution if available
        channel_dist = data.get("channelDistribution", data.get("channelData"))
        channel_dist_json = json.dumps(channel_dist, ensure_ascii=False) if channel_dist else None

        await self.pool.execute(
            """
            INSERT INTO qnh_daily_metrics
                (tenant_id, metric_date, channel, store_id,
                 valid_order_amount, valid_order_count, avg_order_value,
                 net_profit, online_gross_profit,
                 paid_amount, paid_avg_order_value, product_sales_amount,
                 packaging_fee, delivery_fee, customer_count,
                 product_sell_through_rate, overtime_rate, stockout_refund_rate,
                 turnover_days, stockout_loss,
                 channel_distribution, extra, synced_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,NOW())
            ON CONFLICT (metric_date, channel, store_id) DO UPDATE SET
                valid_order_amount = EXCLUDED.valid_order_amount,
                valid_order_count = EXCLUDED.valid_order_count,
                avg_order_value = EXCLUDED.avg_order_value,
                net_profit = EXCLUDED.net_profit,
                online_gross_profit = EXCLUDED.online_gross_profit,
                paid_amount = EXCLUDED.paid_amount,
                paid_avg_order_value = EXCLUDED.paid_avg_order_value,
                product_sales_amount = EXCLUDED.product_sales_amount,
                packaging_fee = EXCLUDED.packaging_fee,
                delivery_fee = EXCLUDED.delivery_fee,
                customer_count = EXCLUDED.customer_count,
                product_sell_through_rate = EXCLUDED.product_sell_through_rate,
                overtime_rate = EXCLUDED.overtime_rate,
                stockout_refund_rate = EXCLUDED.stockout_refund_rate,
                turnover_days = EXCLUDED.turnover_days,
                stockout_loss = EXCLUDED.stockout_loss,
                channel_distribution = EXCLUDED.channel_distribution,
                extra = EXCLUDED.extra,
                synced_at = NOW()
            """,
            self.client.tenant_id,
            metric_date,
            channel,
            str(self.client.poi_ids[0]) if self.client.poi_ids else None,
            _num(data, "validOrderAmount", "effectiveOrderAmount"),
            _int(data, "validOrderCount", "effectiveOrderCount"),
            _num(data, "avgOrderValue", "customerPrice"),
            _num(data, "netProfit"),
            _num(data, "onlineGrossProfit", "grossProfit"),
            _num(data, "paidAmount", "actualPayAmount"),
            _num(data, "paidAvgOrderValue"),
            _num(data, "productSalesAmount", "goodsSalesAmount"),
            _num(data, "packagingFee", "boxFee"),
            _num(data, "deliveryFee", "shippingFee"),
            _int(data, "customerCount", "buyerCount"),
            _num(data, "productSellThroughRate", "sellRate"),
            _num(data, "overtimeRate"),
            _num(data, "stockoutRefundRate"),
            _num(data, "turnoverDays"),
            _num(data, "stockoutLoss"),
            channel_dist_json,
            json.dumps(data, ensure_ascii=False, default=str),
        )


def _num(data: dict, *keys: str) -> Any:
    for k in keys:
        v = data.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return None


def _int(data: dict, *keys: str) -> Any:
    for k in keys:
        v = data.get(k)
        if v is not None:
            try:
                return int(v)
            except (ValueError, TypeError):
                pass
    return None
