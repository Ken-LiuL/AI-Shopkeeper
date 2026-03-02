"""Auth dependency injection."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.models import UserInfo
from src.auth.utils import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserInfo:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期或无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserInfo(
        user_id=payload.get("sub", ""),
        username=payload.get("username", ""),
        tenant_id=payload.get("tenant_id", "default"),
        role=payload.get("role", "user"),
    )
