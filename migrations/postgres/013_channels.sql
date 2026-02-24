-- 013: 渠道流量分布表
-- 数据源: 牵牛花 数据分析-渠道对比

CREATE TABLE IF NOT EXISTS qnh_traffic_channels (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       VARCHAR(32) NOT NULL,
    date            DATE NOT NULL,
    channel         VARCHAR(32) NOT NULL,   -- meituan / eleme / jddj
    exposure        BIGINT DEFAULT 0,       -- 曝光数
    clicks          BIGINT DEFAULT 0,       -- 点击数
    orders          INT DEFAULT 0,          -- 下单数
    click_rate      NUMERIC(6,4) DEFAULT 0, -- 点击率
    conversion_rate NUMERIC(6,4) DEFAULT 0, -- 转化率
    gmv             NUMERIC(12,2) DEFAULT 0,-- GMV归因
    new_customers   INT DEFAULT 0,
    extra           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, date, channel)
);

CREATE INDEX idx_traffic_channels_date ON qnh_traffic_channels(date);
CREATE INDEX idx_traffic_channels_channel ON qnh_traffic_channels(channel);
