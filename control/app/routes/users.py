"""用户管理：管理员查看 / 禁用用户。

对应 SPEC §3：users 表由注册流程写入，管理员可读与禁用。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Conversation, User, UserRole
from ..security import CurrentAdmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])


class UserAdminOut(BaseModel):
    id: int
    username: str
    email: str | None
    display_name: str | None
    role: str
    disabled: bool
    created_at: datetime | None
    last_login_at: datetime | None
    conversation_count: int = 0

    model_config = {"from_attributes": True}


class UserUpdateIn(BaseModel):
    disabled: bool | None = None
    display_name: str | None = None
    role: str | None = None  # "user" | "admin"


@router.get("", response_model=list[UserAdminOut])
async def list_users(
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[UserAdminOut]:
    # 一次聚合出每个用户的会话数，避免 N+1
    counts = dict(
        (
            await session.execute(
                select(Conversation.user_id, func.count(Conversation.id))
                .where(Conversation.deleted_at.is_(None))
                .group_by(Conversation.user_id)
            )
        ).all()
    )

    users = (
        await session.execute(select(User).order_by(User.created_at.desc()))
    ).scalars().all()

    out: list[UserAdminOut] = []
    for u in users:
        item = UserAdminOut.model_validate(u)
        item.conversation_count = int(counts.get(u.id, 0))
        out.append(item)
    return out


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: int,
    body: UserUpdateIn,
    current: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserAdminOut:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if body.disabled is not None:
        if body.disabled and user.id == current.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "不能禁用自己的账号")
        user.disabled = body.disabled
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.role is not None:
        if body.role not in (UserRole.USER, UserRole.ADMIN):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "role 只能是 user 或 admin")
        # 不能修改自己的权限（用户拍板）：无论升降级，避免误操作导致无管理员或权限混乱。
        if user.id == current.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "不能修改自己的权限，请由其他管理员操作"
            )
        # 降级他人时，不能移除最后一名管理员
        if body.role != UserRole.ADMIN and user.role == UserRole.ADMIN:
            admin_count = (
                await session.execute(
                    select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
                )
            ).scalar_one()
            if admin_count <= 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "不能移除最后一名管理员")
        user.role = body.role

    await session.commit()
    await session.refresh(user)

    item = UserAdminOut.model_validate(user)
    item.conversation_count = int(
        (
            await session.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.user_id == user.id, Conversation.deleted_at.is_(None)
                )
            )
        ).scalar_one()
    )
    return item
