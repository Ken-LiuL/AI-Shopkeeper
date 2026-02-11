"""Alert SQL queries."""

LIST_ALERTS = """
SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT 100
"""

GET_ALERT = "SELECT * FROM alerts WHERE alert_id = $1"

UPDATE_ALERT_STATUS = """
UPDATE alerts SET status = $1,
    resolved_at = CASE WHEN $1 = 'resolved' THEN NOW() ELSE resolved_at END
WHERE alert_id = $2 RETURNING *
"""

ALERT_STATS = """
SELECT severity, status, COUNT(*)::int AS count
FROM alerts
GROUP BY severity, status
"""

RECENT_ALERTS_BY_SEVERITY = """
SELECT severity, COUNT(*)::int AS count
FROM alerts
WHERE status = 'pending'
GROUP BY severity
"""
