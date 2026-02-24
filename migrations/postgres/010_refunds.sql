-- 010: 退款/售后明细表
-- 数据源: 牵牛花 售后管理模块

CREATE TABLE IF NOT EXISTS qnh_refunds (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       VARCHAR(32) NOT NULL,
    refund_id       VARCHAR(64) NOT NULL UNIQUE,
    order_id        VARCHAR(64),
    channel         VARCHAR(32),
    sku_id          VARCHAR(64),
    sku_name        VARCHAR(256),
    refund_reason   VARCHAR(128),          -- 缺货 / 质量问题 / 配送问题 / 客户取消 / 其他
    refund_amount   NUMERIC(10,2),
    refund_status   VARCHAR(32),           -- pending / approved / rejected / completed
    refund_time     TIMESTAMPTZ,
    resolved_time   TIMESTAMPTZ,
    extra           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refunds_tenant ON qnh_refunds(tenant_id);
CREATE INDEX idx_refunds_order ON qnh_refunds(order_id);
CREATE INDEX idx_refunds_sku ON qnh_refunds(sku_id);
CREATE INDEX idx_refunds_reason ON qnh_refunds(refund_reason);
CREATE INDEX idx_refunds_time ON qnh_refunds(refund_time);
CREATE INDEX idx_refunds_status ON qnh_refunds(refund_status);
