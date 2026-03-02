-- 额外的索引优化和表优化
-- 为了保持迁移连续性

-- 优化qnh_products表的查询性能
CREATE INDEX IF NOT EXISTS idx_qnh_products_category ON qnh_products(category);
CREATE INDEX IF NOT EXISTS idx_qnh_products_status ON qnh_products(status);
CREATE INDEX IF NOT EXISTS idx_qnh_products_updated ON qnh_products(updated_at);

-- 优化qnh_orders表的查询性能
CREATE INDEX IF NOT EXISTS idx_qnh_orders_poi_id ON qnh_orders(poi_id);
CREATE INDEX IF NOT EXISTS idx_qnh_orders_order_time ON qnh_orders(order_time);

-- 优化cs_sessions表的查询性能
CREATE INDEX IF NOT EXISTS idx_cs_sessions_customer_id ON cs_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_cs_sessions_created_at ON cs_sessions(created_at);

SELECT 'Additional indexes created for better performance' as status;
