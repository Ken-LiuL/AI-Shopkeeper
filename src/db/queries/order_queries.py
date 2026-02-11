"""Order SQL queries."""

ORDER_STATS_BY_DATE = """
SELECT order_time::date AS date, COUNT(*)::int AS order_count,
       SUM(total_amount) AS total_amount
FROM orders
WHERE order_time >= CURRENT_DATE - make_interval(days => $1)
GROUP BY order_time::date ORDER BY date
"""

ORDER_STATS_BY_STATUS = """
SELECT status, COUNT(*)::int AS count, SUM(total_amount) AS total_amount
FROM orders
WHERE order_time >= CURRENT_DATE - make_interval(days => $1)
GROUP BY status
"""

TOP_ORDERED_PRODUCTS = """
SELECT oi.product_id, p.name, SUM(oi.quantity)::int AS total_qty,
       SUM(oi.unit_price * oi.quantity) AS total_revenue
FROM order_items oi JOIN products p ON oi.product_id = p.product_id
JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_time >= CURRENT_DATE - make_interval(days => $1)
GROUP BY oi.product_id, p.name
ORDER BY total_qty DESC LIMIT $2
"""
