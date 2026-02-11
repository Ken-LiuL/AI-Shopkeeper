"""Product SQL queries."""

LIST_PRODUCTS = """
SELECT * FROM products {where} ORDER BY created_at DESC LIMIT ${{limit}} OFFSET ${{offset}}
"""

COUNT_PRODUCTS = "SELECT COUNT(*) FROM products {where}"

GET_PRODUCT = "SELECT * FROM products WHERE product_id = $1"

CREATE_PRODUCT = """
INSERT INTO products (product_id, name, barcode, category, brand, description,
                      cost_price, retail_price, stock, status, created_at, updated_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),NOW()) RETURNING *
"""

PRODUCT_SALES = """
SELECT sale_date AS date, quantity, revenue FROM sales_history
WHERE product_id = $1 ORDER BY sale_date DESC LIMIT 90
"""

SEARCH_PRODUCTS = """
SELECT * FROM products
WHERE (name ILIKE $1 OR barcode ILIKE $1)
ORDER BY created_at DESC LIMIT $2 OFFSET $3
"""
