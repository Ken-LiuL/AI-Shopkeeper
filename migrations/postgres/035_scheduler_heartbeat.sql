-- 032_scheduler_heartbeat.sql
-- 定时任务心跳记录表：持久化追踪各调度任务的执行状态
-- 解决 APScheduler 在 fly.io auto_stop 下休眠丢失任务的可观测性问题

CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
    task_name   TEXT PRIMARY KEY,
    last_run    TIMESTAMPTZ,
    next_run    TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'unknown',
    -- status 取值: 'unknown' | 'running' | 'success' | 'failed'
    error_msg   TEXT,
    run_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE scheduler_heartbeat IS '定时任务心跳记录，追踪各定时任务的执行状态与运行历史';
COMMENT ON COLUMN scheduler_heartbeat.task_name  IS '任务唯一标识，对应 APScheduler job id';
COMMENT ON COLUMN scheduler_heartbeat.last_run   IS '最近一次开始执行时间';
COMMENT ON COLUMN scheduler_heartbeat.next_run   IS '下次预计执行时间（由调度器计算）';
COMMENT ON COLUMN scheduler_heartbeat.status     IS '最近执行状态：unknown/running/success/failed';
COMMENT ON COLUMN scheduler_heartbeat.error_msg  IS '最近失败时的错误信息';
COMMENT ON COLUMN scheduler_heartbeat.run_count  IS '累计执行次数';
COMMENT ON COLUMN scheduler_heartbeat.updated_at IS '记录最后更新时间';

CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat_status ON scheduler_heartbeat (status);
CREATE INDEX IF NOT EXISTS idx_scheduler_heartbeat_last_run ON scheduler_heartbeat (last_run DESC);
