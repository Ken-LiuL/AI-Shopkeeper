-- 009: 客户/消费排行表
-- 数据源: 牵牛花 客户管理模块

CREATE TABLE IF NOT EXISTS qnh_customers (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           VARCHAR(32) NOT NULL,
    customer_id         VARCHAR(64) NOT NULL UNIQUE,
    nickname            VARCHAR(128),
    phone_tail          VARCHAR(16),
    channel             VARCHAR(32),
    total_amount        NUMERIC(12,2) DEFAULT 0,
    order_count         INT DEFAULT 0,
    avg_order_amount    NUMERIC(10,2) DEFAULT 0,
    last_order_time     TIMESTAMPTZ,
    first_order_time    TIMESTAMPTZ,
    repurchase_rate     NUMERIC(5,4) DEFAULT 0,  -- 复购率 0-1
    address_city        VARCHAR(64),
    address_district    VARCHAR(64),
    tags                JSONB,                    -- 标签: VIP / 新客 / 流失风险
    extra               JSONB,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_customers_tenant ON qnh_customers(tenant_id);
CREATE INDEX idx_customers_amount ON qnh_customers(total_amount DESC);
CREATE INDEX idx_customers_last_order ON qnh_customers(last_order_time);
CREATE INDEX idx_customers_repurchase ON qnh_customers(repurchase_rate DESC);
