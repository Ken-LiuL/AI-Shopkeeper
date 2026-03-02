"""Seed default admin user after migrations."""

from __future__ import annotations

import logging

from src.auth.utils import get_password_hash
from src.db import postgres as pg_db

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


async def seed_admin_user() -> None:
    """Ensure the default admin user exists with the correct password hash."""
    try:
        row = await pg_db.fetchrow(
            "SELECT user_id, password_hash FROM users WHERE username = $1",
            DEFAULT_ADMIN_USERNAME,
        )
        hashed = get_password_hash(DEFAULT_ADMIN_PASSWORD)
        if row is None:
            await pg_db.execute(
                """
                INSERT INTO users (user_id, username, password_hash, tenant_id, role)
                VALUES ('user-admin-001', $1, $2, 'default', 'admin')
                ON CONFLICT (username) DO NOTHING
                """,
                DEFAULT_ADMIN_USERNAME,
                hashed,
            )
            logger.info("默认管理员账号已创建: %s", DEFAULT_ADMIN_USERNAME)
        elif row["password_hash"] == "__PLACEHOLDER__":
            await pg_db.execute(
                "UPDATE users SET password_hash = $1 WHERE username = $2",
                hashed,
                DEFAULT_ADMIN_USERNAME,
            )
            logger.info("默认管理员密码已初始化")
        else:
            logger.info("管理员账号已存在，跳过初始化")
    except Exception as e:
        logger.error("初始化管理员账号失败: %s", e)
