-- 008: 营销活动表
-- 数据源: 牵牛花 活动管理模块

CREATE TABLE IF NOT EXISTS qnh_promotions (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       VARCHAR(32) NOT NULL,
    promotion_id    VARCHAR(64) NOT NULL UNIQUE,
    channel         VARCHAR(32),           -- meituan / eleme / jddj
    promotion_type  VARCHAR(32),           -- 满减 / 折扣 / 秒杀 / 买赠 / 优惠券
    title           VARCHAR(256),
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    status          VARCHAR(32),           -- active / ended / paused / pending
    discount_rule   JSONB,                 -- 折扣规则详情 {"threshold":30,"discount":5}
    product_ids     JSONB,                 -- 参与商品ID列表
    effect_data     JSONB,                 -- 活动效果: 订单数/GMV/ROI
    extra           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_promotions_tenant ON qnh_promotions(tenant_id);
CREATE INDEX idx_promotions_status ON qnh_promotions(status);
CREATE INDEX idx_promotions_time ON qnh_promotions(start_time, end_time);
CREATE INDEX idx_promotions_type ON qnh_promotions(promotion_type);
