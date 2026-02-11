"""Database Skill — PostgreSQL CRUD for products, orders, alerts, stats."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Pydantic Models ──────────────────────────────────────────────────────────

class Product(BaseModel):
    product_id: str
    name: str
    category: str = ""
    price: float = 0.0
    cost: float = 0.0
    stock: int = 0
    status: str = "active"  # active/inactive/discontinued
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ProductCreate(BaseModel):
    name: str
    category: str = ""
    price: float = 0.0
    cost: float = 0.0
    stock: int = 0
    description: str = ""

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    stock: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None

class Order(BaseModel):
    order_id: str
    product_id: str
    product_name: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    total_amount: float = 0.0
    order_date: Optional[datetime] = None
    status: str = "completed"

class SalesStats(BaseModel):
    product_id: str
    product_name: str = ""
    total_quantity: int = 0
    total_revenue: float = 0.0
    total_cost: float = 0.0
    gross_profit: float = 0.0
    gross_margin: float = 0.0
    order_count: int = 0

class AlertRecord(BaseModel):
    alert_id: Optional[int] = None
    product_id: str
    alert_type: str  # sales_drop/price_gap/stockout/margin_warning/zero_sales
    severity: str = "warning"  # critical/warning/info
    title: str = ""
    description: str = ""
    root_cause: str = ""
    suggestion: str = ""
    status: str = "open"  # open/acknowledged/resolved
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

class AlertCreate(BaseModel):
    product_id: str
    alert_type: str
    severity: str = "warning"
    title: str = ""
    description: str = ""
    root_cause: str = ""
    suggestion: str = ""

class SelectionRun(BaseModel):
    run_id: Optional[int] = None
    trigger: str = "scheduled"  # scheduled/manual
    status: str = "running"  # running/completed/failed
    total_evaluated: int = 0
    recommended_count: int = 0
    top_score: float = 0.0
    results: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DatabaseSkill:
    """PostgreSQL CRUD 技能。"""

    def __init__(self, pool: Any = None):
        """
        Args:
            pool: asyncpg.Pool instance (injected).
        """
        self._pool = pool

    async def _fetch(self, query: str, *args: Any) -> List[Dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]

    async def _fetchrow(self, query: str, *args: Any) -> Optional[Dict[str, Any]]:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def _execute(self, query: str, *args: Any) -> str:
        if self._pool is None:
            return ""
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    # ── 商品 CRUD ────────────────────────────────────────────────────────

    async def get_product(self, product_id: str) -> Optional[Product]:
        row = await self._fetchrow(
            "SELECT * FROM products WHERE product_id = $1", product_id
        )
        return Product(**row) if row else None

    async def list_products(
        self,
        category: Optional[str] = None,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Product]:
        conditions = ["status = $1"]
        params: list[Any] = [status]
        idx = 2
        if category:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1
        params.extend([limit, offset])
        query = f"""
        SELECT * FROM products
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """
        rows = await self._fetch(query, *params)
        return [Product(**r) for r in rows]

    async def create_product(self, data: ProductCreate) -> Optional[Product]:
        row = await self._fetchrow(
            """
            INSERT INTO products (name, category, price, cost, stock, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            data.name, data.category, data.price, data.cost, data.stock, data.description,
        )
        return Product(**row) if row else None

    async def update_product(self, product_id: str, data: ProductUpdate) -> Optional[Product]:
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return await self.get_product(product_id)
        set_clauses = [f"{k} = ${i+2}" for i, k in enumerate(updates)]
        values = list(updates.values())
        query = f"""
        UPDATE products SET {', '.join(set_clauses)}, updated_at = NOW()
        WHERE product_id = $1
        RETURNING *
        """
        row = await self._fetchrow(query, product_id, *values)
        return Product(**row) if row else None

    async def delete_product(self, product_id: str) -> bool:
        result = await self._execute(
            "UPDATE products SET status = 'discontinued' WHERE product_id = $1",
            product_id,
        )
        return "UPDATE 1" in result

    # ── 订单查询 ─────────────────────────────────────────────────────────

    async def get_orders(
        self,
        product_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 50,
    ) -> List[Order]:
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1
        if product_id:
            conditions.append(f"o.product_id = ${idx}")
            params.append(product_id)
            idx += 1
        if start_date:
            conditions.append(f"o.order_date >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date:
            conditions.append(f"o.order_date <= ${idx}")
            params.append(end_date)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        query = f"""
        SELECT o.*, p.name AS product_name
        FROM orders o JOIN products p ON o.product_id = p.product_id
        {where}
        ORDER BY o.order_date DESC
        LIMIT ${idx}
        """
        rows = await self._fetch(query, *params)
        return [Order(**r) for r in rows]

    async def get_daily_sales(
        self,
        product_id: str,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """获取商品每日销量（供 Prophet 训练用）。"""
        rows = await self._fetch(
            """
            SELECT order_date::date AS ds, SUM(quantity) AS y
            FROM orders
            WHERE product_id = $1
              AND order_date >= CURRENT_DATE - $2 * INTERVAL '1 day'
            GROUP BY ds ORDER BY ds
            """,
            product_id, days,
        )
        return rows

    # ── 统计分析 ─────────────────────────────────────────────────────────

    async def get_sales_stats(
        self,
        product_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[SalesStats]:
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1
        if product_id:
            conditions.append(f"o.product_id = ${idx}")
            params.append(product_id)
            idx += 1
        if start_date:
            conditions.append(f"o.order_date >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date:
            conditions.append(f"o.order_date <= ${idx}")
            params.append(end_date)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
        SELECT
            o.product_id,
            p.name AS product_name,
            SUM(o.quantity) AS total_quantity,
            SUM(o.total_amount) AS total_revenue,
            SUM(o.quantity * p.cost) AS total_cost,
            SUM(o.total_amount) - SUM(o.quantity * p.cost) AS gross_profit,
            CASE WHEN SUM(o.total_amount) > 0
                THEN (SUM(o.total_amount) - SUM(o.quantity * p.cost)) / SUM(o.total_amount)
                ELSE 0 END AS gross_margin,
            COUNT(DISTINCT o.order_id) AS order_count
        FROM orders o JOIN products p ON o.product_id = p.product_id
        {where}
        GROUP BY o.product_id, p.name
        ORDER BY total_revenue DESC
        """
        rows = await self._fetch(query, *params)
        return [SalesStats(**r) for r in rows]

    # ── 预警记录 CRUD ────────────────────────────────────────────────────

    async def create_alert(self, data: AlertCreate) -> Optional[AlertRecord]:
        row = await self._fetchrow(
            """
            INSERT INTO alerts (product_id, alert_type, severity, title, description, root_cause, suggestion)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            data.product_id, data.alert_type, data.severity,
            data.title, data.description, data.root_cause, data.suggestion,
        )
        return AlertRecord(**row) if row else None

    async def get_alerts(
        self,
        product_id: Optional[str] = None,
        status: str = "open",
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> List[AlertRecord]:
        conditions = ["status = $1"]
        params: list[Any] = [status]
        idx = 2
        if product_id:
            conditions.append(f"product_id = ${idx}")
            params.append(product_id)
            idx += 1
        if severity:
            conditions.append(f"severity = ${idx}")
            params.append(severity)
            idx += 1
        params.append(limit)
        query = f"""
        SELECT * FROM alerts
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT ${idx}
        """
        rows = await self._fetch(query, *params)
        return [AlertRecord(**r) for r in rows]

    async def resolve_alert(self, alert_id: int) -> bool:
        result = await self._execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = NOW() WHERE alert_id = $1",
            alert_id,
        )
        return "UPDATE 1" in result

    async def acknowledge_alert(self, alert_id: int) -> bool:
        result = await self._execute(
            "UPDATE alerts SET status = 'acknowledged' WHERE alert_id = $1",
            alert_id,
        )
        return "UPDATE 1" in result

    # ── 选品运行记录 ─────────────────────────────────────────────────────

    async def create_selection_run(self, trigger: str = "scheduled") -> Optional[SelectionRun]:
        row = await self._fetchrow(
            """
            INSERT INTO selection_runs (trigger, status) VALUES ($1, 'running')
            RETURNING *
            """,
            trigger,
        )
        return SelectionRun(**row) if row else None

    async def complete_selection_run(
        self,
        run_id: int,
        total_evaluated: int,
        recommended_count: int,
        top_score: float,
        results: Optional[Dict[str, Any]] = None,
    ) -> bool:
        import json
        result = await self._execute(
            """
            UPDATE selection_runs
            SET status = 'completed', completed_at = NOW(),
                total_evaluated = $2, recommended_count = $3,
                top_score = $4, results = $5
            WHERE run_id = $1
            """,
            run_id, total_evaluated, recommended_count, top_score,
            json.dumps(results) if results else None,
        )
        return "UPDATE 1" in result

    async def fail_selection_run(self, run_id: int, error: str = "") -> bool:
        result = await self._execute(
            """
            UPDATE selection_runs
            SET status = 'failed', completed_at = NOW(),
                results = jsonb_build_object('error', $2)
            WHERE run_id = $1
            """,
            run_id, error,
        )
        return "UPDATE 1" in result

    async def get_latest_selection_runs(self, limit: int = 10) -> List[SelectionRun]:
        rows = await self._fetch(
            "SELECT * FROM selection_runs ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        return [SelectionRun(**r) for r in rows]
