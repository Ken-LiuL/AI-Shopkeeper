-- 046: 为 order_items 添加唯一约束，防止重复导入产生重复明细
-- 先清除可能已有的重复数据
DELETE FROM order_items a
    USING order_items b
WHERE a.id > b.id
  AND a.order_id = b.order_id
  AND a.product_id = b.product_id;

-- 添加唯一约束
ALTER TABLE order_items
    ADD CONSTRAINT uq_order_items_order_product UNIQUE (order_id, product_id);
