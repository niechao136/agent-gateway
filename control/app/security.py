"""鉴权：密码哈希 + JWT（带 scope 隔离）+ FastAPI 依赖。

关键设计（SPEC §3.5）：
- JWT 用同一个签名密钥，但用 `scope` claim 区分 user / admin
- get_current_user 必须显式拒绝 scope=admin 的 token，反之亦然
- bcrypt 只接受前 72 字节，必须显式截断（bcrypt 5.x 超长会抛错）
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_session
from .models import User

_settings = get_settings()

_BCRYPT_MAX_BYTES = 72

Scope = Literal["user", "admin"]

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
def create_access_token(subject: str, scope: Scope) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=_settings.jwt_expire_minutes)
    payload = {"sub": subject, "scope": scope, "exp": expire}
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
async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """对话页用：只接受 scope=user 的 token。"""
    payload = _extract(creds)
    if payload.get("scope") != "user":
        # 管理员 token 不能当用户 token 用（语义隔离）
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要用户身份"
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证缺少主体")

    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or user.disabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


async def get_current_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """管理中心用：只接受 scope=admin 的 token。"""
    payload = _extract(creds)
    if payload.get("scope") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员身份"
        )
    return payload.get("sub") or "admin"


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[str, Depends(get_current_admin)]
