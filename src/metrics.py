"""Prometheus metrics for AI Store Manager."""

from prometheus_client import Counter, Gauge, Histogram

# ── LLM 指标 ────────────────────────────────────────────────────────────────

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "type"],  # token category: input/output
)

llm_request_duration = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration in seconds",
    ["model"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# ── Agent 执行指标 ──────────────────────────────────────────────────────────

agent_execution_duration = Histogram(
    "agent_execution_duration_seconds",
    "Agent execution duration in seconds",
    ["agent_type"],  # selection/customer_service/alert/bundle/listing
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

agent_execution_total = Counter(
    "agent_execution_total",
    "Total agent executions",
    ["agent_type", "status"],  # status: success/error
)

# ── 预警指标 ────────────────────────────────────────────────────────────────

alerts_triggered_total = Counter(
    "alerts_triggered_total",
    "Total alerts triggered",
    ["alert_type", "severity"],
)

alerts_active = Gauge(
    "alerts_active",
    "Number of active (pending) alerts",
    ["severity"],
)

# ── 选品指标 ────────────────────────────────────────────────────────────────

selection_recommendations_total = Counter(
    "selection_recommendations_total",
    "Total selection recommendations generated",
    ["priority"],  # strong_recommend/recommend/optional
)

selection_run_total = Counter(
    "selection_run_total",
    "Total selection runs",
    ["trigger", "status"],  # trigger: scheduled/manual, status: completed/failed
)

# ── 客服指标 ────────────────────────────────────────────────────────────────

customer_service_requests_total = Counter(
    "customer_service_requests_total",
    "Total customer service requests",
    ["intent", "route"],  # route: faq/search/human
)

customer_service_human_handoff_total = Counter(
    "customer_service_human_handoff_total",
    "Total human handoff requests",
    ["reason"],
)

# ── 套餐指标 ────────────────────────────────────────────────────────────────

bundle_generated_total = Counter(
    "bundle_generated_total",
    "Total bundles generated",
    ["status"],  # approved/rejected
)

# ── 数据库指标 ──────────────────────────────────────────────────────────────

db_query_duration = Histogram(
    "db_query_duration_seconds",
    "Database query duration",
    ["db", "operation"],  # db: postgres/neo4j/redis, operation: read/write
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)


# ── Helper functions ────────────────────────────────────────────────────────


def record_agent_execution(agent_type: str, duration: float, success: bool = True) -> None:
    """记录 Agent 执行指标"""
    agent_execution_duration.labels(agent_type=agent_type).observe(duration)
    agent_execution_total.labels(
        agent_type=agent_type,
        status="success" if success else "error",
    ).inc()


def record_alert_triggered(alert_type: str, severity: str) -> None:
    """记录预警触发指标"""
    alerts_triggered_total.labels(alert_type=alert_type, severity=severity).inc()


def update_active_alerts(critical: int, warning: int, info: int) -> None:
    """更新活跃预警数量"""
    alerts_active.labels(severity="critical").set(critical)
    alerts_active.labels(severity="warning").set(warning)
    alerts_active.labels(severity="info").set(info)
