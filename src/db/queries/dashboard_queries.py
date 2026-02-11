"""Dashboard SQL queries."""

OVERVIEW_TOTAL_PRODUCTS = "SELECT COUNT(*) FROM products WHERE status = 'active'"

OVERVIEW_TODAY_ORDERS = "SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE"

OVERVIEW_PENDING_ALERTS = "SELECT COUNT(*) FROM alerts WHERE status = 'pending'"

SALES_TREND_30D = """
SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
FROM sales_history
WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY sale_date ORDER BY sale_date
"""

TOP_PRODUCTS_30D = """
SELECT sh.product_id, p.name, SUM(sh.quantity)::int AS total_sales, SUM(sh.revenue) AS revenue
FROM sales_history sh JOIN products p ON sh.product_id = p.product_id
WHERE sh.sale_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY sh.product_id, p.name
ORDER BY total_sales DESC LIMIT 10
"""

# QNH daily metrics based overview (richer data from 牵牛花)
QNH_OVERVIEW = """
SELECT metric_date, valid_order_amount, valid_order_count, avg_order_value,
       net_profit, customer_count, channel_distribution
FROM qnh_daily_metrics
WHERE metric_date = CURRENT_DATE AND channel IS NULL
LIMIT 1
"""

QNH_SALES_TREND = """
SELECT metric_date AS date, valid_order_count AS orders,
       valid_order_amount AS revenue, avg_order_value
FROM qnh_daily_metrics
WHERE metric_date >= CURRENT_DATE - $1::int
  AND channel IS NULL
ORDER BY metric_date
"""
