-- 去重 qnh_products：按 spu_id 分组，保留 id 最大的记录
DELETE FROM qnh_products
WHERE id NOT IN (
    SELECT MAX(id) FROM qnh_products GROUP BY spu_id, sku_id
);
