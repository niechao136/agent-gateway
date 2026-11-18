"""用户体系：注册 / 登录 / 当前用户。

v2 鉴权模型（SPEC-v2 决策 1）：单一用户体系 + role 字段。
登录入口只有 /api/auth/login，admin 与普通用户共用，区别在 token 的 role claim。
"""

import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import User
from ..security import CurrentUser, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

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
    role: str

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
    if not _registration_allowed():
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

    token = create_access_token(user.username, user.role)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


def _registration_allowed() -> bool:
    from ..config import get_settings

    return get_settings().allow_registration


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

    token = create_access_token(user.username, user.role)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """修改当前登录用户的密码：必须校验原密码，成功返回（旧 token 继续有效至过期）。"""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="原密码不正确"
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="新密码不能与原密码相同",
        )
    user.password_hash = hash_password(body.new_password)
    await session.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
