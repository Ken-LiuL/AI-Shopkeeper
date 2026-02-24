-- 011: 财务结算表
-- 数据源: 牵牛花 财务对账模块

CREATE TABLE IF NOT EXISTS qnh_settlements (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           VARCHAR(32) NOT NULL,
    settlement_id       VARCHAR(64) NOT NULL UNIQUE,
    channel             VARCHAR(32),
    period_start        DATE,
    period_end          DATE,
    gross_income        NUMERIC(12,2) DEFAULT 0,   -- 商品收入
    platform_fee        NUMERIC(10,2) DEFAULT 0,   -- 平台扣费(技术服务费)
    delivery_fee        NUMERIC(10,2) DEFAULT 0,   -- 配送费
    commission_fee      NUMERIC(10,2) DEFAULT 0,   -- 佣金
    promotion_fee       NUMERIC(10,2) DEFAULT 0,   -- 活动分摊费用
    packaging_fee       NUMERIC(10,2) DEFAULT 0,   -- 包装费
    other_fee           NUMERIC(10,2) DEFAULT 0,   -- 其他扣费
    net_income          NUMERIC(12,2) DEFAULT 0,   -- 净收入(到手)
    order_count         INT DEFAULT 0,
    fee_details         JSONB,                      -- 扣费明细
    extra               JSONB,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_settlements_tenant ON qnh_settlements(tenant_id);
CREATE INDEX idx_settlements_channel ON qnh_settlements(channel);
CREATE INDEX idx_settlements_period ON qnh_settlements(period_start, period_end);
