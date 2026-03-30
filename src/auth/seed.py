"""Seed default admin user after migrations."""

from __future__ import annotations

import logging
import os

from src.auth.utils import get_password_hash
from src.db import postgres as pg_db

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


async def seed_admin_user() -> None:
    """Ensure the default admin user exists with the correct password hash.

    Password is read from ADMIN_PASSWORD env var. If not set, a random
    password is generated and logged (first-run only).
    """
    try:
        # Ensure users table exists (migration may have been skipped/rolled back)
        await pg_db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
                username    TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                tenant_id   TEXT NOT NULL DEFAULT 'default',
                role        TEXT NOT NULL DEFAULT 'admin',
                created_at  TIMESTAMPTZ DEFAULT now(),
                updated_at  TIMESTAMPTZ DEFAULT now()
            )
        """)

        # Check if admin already exists with a valid password
        existing = await pg_db.fetchrow(
            "SELECT password_hash FROM users WHERE username = $1",
            DEFAULT_ADMIN_USERNAME,
        )
        if existing and existing["password_hash"].startswith("$2"):
            logger.info("管理员账号已存在，跳过 seed")
            return

        # Determine password
        password = DEFAULT_ADMIN_PASSWORD
        if not password:
            import secrets
            password = secrets.token_urlsafe(16)
            logger.warning(
                "⚠️  ADMIN_PASSWORD 未设置，生成随机密码: %s （请立即修改或设置环境变量）",
                password,
            )

        hashed = get_password_hash(password)
        await pg_db.execute(
            """
            INSERT INTO users (user_id, username, password_hash, tenant_id, role)
            VALUES ('user-admin-001', $1, $2, 'default', 'admin')
            ON CONFLICT (username) DO UPDATE SET password_hash = $2
            """,
            DEFAULT_ADMIN_USERNAME,
            hashed,
        )
        logger.info("管理员账号已初始化: %s", DEFAULT_ADMIN_USERNAME)

        # Verify
        row = await pg_db.fetchrow(
            "SELECT user_id, password_hash FROM users WHERE username = $1",
            DEFAULT_ADMIN_USERNAME,
        )
        if row and row["password_hash"].startswith("$2"):
            logger.info("管理员密码 hash 验证通过 ✓")
        else:
            logger.error("管理员密码 hash 异常: %s", row["password_hash"][:20] if row else "no row")
    except Exception as e:
        logger.error("初始化管理员账号失败: %s", e)
