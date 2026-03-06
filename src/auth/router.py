"""Authentication API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.deps import get_current_user
from src.auth.models import LoginRequest, Token, UserInfo
from src.auth.utils import create_access_token, verify_password
from src.db import postgres as pg_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(request: LoginRequest):
    """用户名密码登录，返回 JWT access token。"""
    try:
        row = await pg_db.fetchrow(
            "SELECT id, username, password_hash, role FROM users WHERE username = $1",
            request.username,
        )
    except Exception as e:
        logger.error("DB error during login: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )

    if not row or not verify_password(request.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_access_token(
        {
            "sub": str(row["user_id"]),
            "username": row["username"],
            "tenant_id": "default",
            "role": row["role"],
        }
    )
    return Token(access_token=token)


@router.post("/logout")
async def logout(current_user: UserInfo = Depends(get_current_user)):
    """退出登录（客户端清除 token 即可）。"""
    return {"message": "退出登录成功"}


@router.get("/me", response_model=UserInfo)
async def me(current_user: UserInfo = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user
