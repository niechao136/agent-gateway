"""鉴权：密码哈希 + JWT（role claim）+ FastAPI 依赖。

v2 设计（SPEC-v2 决策 1）：
- 单一 users 表，role 字段区分 user / admin，JWT payload 为 {sub, role, exp}
- get_current_user 接受任意有效登录用户（admin 也算）
- get_current_admin 要求 role == "admin"
- bcrypt 只接受前 72 字节，必须显式截断（bcrypt 5.x 超长会抛错）
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_session
from .models import User, UserRole

_settings = get_settings()

_BCRYPT_MAX_BYTES = 72

_bearer = HTTPBearer(auto_error=False)


# ── 密码 ──────────────────────────────────────────────────
def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT ───────────────────────────────────────────────────
def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=_settings.jwt_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except JWTError:
        return None


def _extract(creds: HTTPAuthorizationCredentials | None) -> dict:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# ── 依赖 ──────────────────────────────────────────────────
async def _load_user(session: AsyncSession, payload: dict) -> User:
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证缺少主体")
    from sqlalchemy import select

    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or user.disabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """任意已登录用户（普通用户与管理员都能过）。"""
    payload = _extract(creds)
    return await _load_user(session, payload)


async def get_current_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """管理操作用：要求 role == admin。"""
    payload = _extract(creds)
    user = await _load_user(session, payload)
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员身份"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]


# ── 归属校验（SPEC-v2 决策 4）──────────────────────────────
def can_modify(user: User, owner_id: int | None) -> bool:
    """管理员全通过；普通用户只能操作自己拥有的资源。"""
    if user.role == UserRole.ADMIN:
        return True
    return owner_id is not None and owner_id == user.id
