-- 去重 qnh_products
-- 1. 删除 sku_id='None' 的重复记录（旧版代码 bug 产生）
DELETE FROM qnh_products WHERE sku_id = 'None';

-- 2. 按 spu_id 去重，保留 id 最大的
DELETE FROM qnh_products
WHERE id NOT IN (
    SELECT MAX(id) FROM qnh_products GROUP BY spu_id
);
