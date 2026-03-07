-- 033: Alert notification transparency
-- Add explicit notification delivery status fields to alerts.

ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS notification_status VARCHAR(32) DEFAULT 'not_sent',
    ADD COLUMN IF NOT EXISTS notification_reason TEXT,
    ADD COLUMN IF NOT EXISTS notification_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_alerts_notification_status ON alerts (notification_status);
