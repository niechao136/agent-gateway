"""用户体系：注册 / 登录 / 当前用户。

鉴权模型见 SPEC §3：users 与 admin 是两套 scope。
"""

import re
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..models import User
from ..security import CurrentUser, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
_settings = get_settings()

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    display_name: str | None = None

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    if not _settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="当前未开放注册"
        )
    if not _USERNAME_RE.match(body.username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="用户名只能包含字母、数字、下划线和连字符，长度 3-64",
        )

    # 用户名或邮箱重复 → 409
    cond = [User.username == body.username]
    if body.email:
        cond.append(User.email == body.email)
    exists = (
        await session.execute(select(User).where(or_(*cond)))
    ).scalar_one_or_none()
    if exists is not None:
        field = "用户名" if exists.username == body.username else "邮箱"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{field}已被占用")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        last_login_at=datetime.now(UTC),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(user.username, "user")
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()

    # 统一错误信息，不泄露"用户是否存在"
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    user.last_login_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(user.username, "user")
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


# ── 管理员登录 ────────────────────────────────────────────
# 管理员不需要单独的数据库表：凭据来自 .env（ADMIN_USERNAME / ADMIN_PASSWORD）。
# 这样个人项目足够，且首次启动即可进入管理中心。
class AdminLoginIn(BaseModel):
    username: str
    password: str


class AdminTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    scope: str = "admin"


@router.post("/admin-login", response_model=AdminTokenOut)
async def admin_login(body: AdminLoginIn) -> AdminTokenOut:
    expected_user = _settings.admin_username
    expected_pass = _settings.admin_password

    if not expected_pass:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置管理员密码（ADMIN_PASSWORD）",
        )

    user_ok = secrets.compare_digest(body.username, expected_user)
    pass_ok = secrets.compare_digest(body.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="管理员账号或密码错误"
        )

    token = create_access_token(expected_user, "admin")
    return AdminTokenOut(access_token=token)
