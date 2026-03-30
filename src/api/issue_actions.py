"""Persistent issue action API for product/order/customer-service work queues."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .schemas import APIResponse, IssueActionLookupRequest, IssueActionRequest

router = APIRouter(prefix="/api/issue-actions", tags=["issue_actions"])
logger = logging.getLogger(__name__)

_ISSUE_ACTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS issue_actions (
    id SERIAL PRIMARY KEY,
    issue_type VARCHAR(100) NOT NULL,
    issue_key TEXT NOT NULL,
    title TEXT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('acknowledged', 'resolved', 'ignored')),
    notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(issue_type, issue_key)
);
CREATE INDEX IF NOT EXISTS idx_issue_actions_type_status ON issue_actions(issue_type, status);
"""


async def _ensure_issue_actions_table() -> None:
    pool = pg.get_pool()
    if pool is None:
        raise RuntimeError("Database connection unavailable")
    async with pool.acquire() as conn:
        await conn.execute(_ISSUE_ACTIONS_TABLE_SQL)


@router.post("/lookup", response_model=APIResponse[list[dict]])
async def lookup_issue_actions(body: IssueActionLookupRequest) -> APIResponse[list[dict]]:
    if not body.issues:
        return APIResponse(data=[])

    try:
        await _ensure_issue_actions_table()
        pool = pg.get_pool()
        assert pool is not None

        keys = [(item.issue_type, item.issue_key) for item in body.issues]
        rows = await pool.fetch(
            """
            SELECT issue_type, issue_key, title, status, notes, metadata, created_at, updated_at
            FROM issue_actions
            WHERE (issue_type, issue_key) IN (
                SELECT * FROM UNNEST($1::text[], $2::text[])
            )
            """,
            [item[0] for item in keys],
            [item[1] for item in keys],
        )
        return APIResponse(data=[dict(row) for row in rows])
    except Exception as exc:
        logger.error("Failed to lookup issue actions: %s", exc)
        return APIResponse(success=False, data=[], message="Failed to lookup issue actions")


@router.get("", response_model=APIResponse[list[dict]])
async def list_issue_actions(
    issue_type: str = Query(..., min_length=1),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> APIResponse[list[dict]]:
    try:
        await _ensure_issue_actions_table()
        pool = pg.get_pool()
        assert pool is not None

        if status:
          rows = await pool.fetch(
              """
              SELECT issue_type, issue_key, title, status, notes, metadata, created_at, updated_at
              FROM issue_actions
              WHERE issue_type = $1 AND status = $2
              ORDER BY updated_at DESC NULLS LAST, created_at DESC
              LIMIT $3
              """,
              issue_type,
              status,
              limit,
          )
        else:
          rows = await pool.fetch(
              """
              SELECT issue_type, issue_key, title, status, notes, metadata, created_at, updated_at
              FROM issue_actions
              WHERE issue_type = $1
              ORDER BY updated_at DESC NULLS LAST, created_at DESC
              LIMIT $2
              """,
              issue_type,
              limit,
          )
        return APIResponse(data=[dict(row) for row in rows])
    except Exception as exc:
        logger.error("Failed to list issue actions: %s", exc)
        return APIResponse(success=False, data=[], message="Failed to list issue actions")


@router.post("", response_model=APIResponse[dict])
async def upsert_issue_action(body: IssueActionRequest) -> APIResponse[dict]:
    try:
        await _ensure_issue_actions_table()
        pool = pg.get_pool()
        assert pool is not None

        row = await pool.fetchrow(
            """
            INSERT INTO issue_actions (
                issue_type,
                issue_key,
                title,
                status,
                notes,
                metadata,
                created_at,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
            ON CONFLICT (issue_type, issue_key) DO UPDATE SET
                title = COALESCE(EXCLUDED.title, issue_actions.title),
                status = EXCLUDED.status,
                notes = COALESCE(EXCLUDED.notes, issue_actions.notes),
                metadata = COALESCE(EXCLUDED.metadata, issue_actions.metadata),
                updated_at = NOW()
            RETURNING issue_type, issue_key, title, status, notes, metadata, created_at, updated_at
            """,
            body.issue_type,
            body.issue_key,
            body.title,
            body.status,
            body.notes,
            json.dumps(body.metadata or {}),
        )
        return APIResponse(data=dict(row), message="Issue action updated")
    except Exception as exc:
        logger.error("Failed to update issue action: %s", exc)
        return APIResponse(success=False, data={}, message="Failed to update issue action")
