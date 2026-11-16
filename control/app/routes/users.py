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
from ..models import Conversation, User
from ..security import CurrentAdmin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])


class UserAdminOut(BaseModel):
    id: int
    username: str
    email: str | None
    display_name: str | None
    disabled: bool
    created_at: datetime | None
    last_login_at: datetime | None
    conversation_count: int = 0

    model_config = {"from_attributes": True}


class UserUpdateIn(BaseModel):
    disabled: bool | None = None
    display_name: str | None = None


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
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserAdminOut:
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if body.disabled is not None:
        user.disabled = body.disabled
    if body.display_name is not None:
        user.display_name = body.display_name

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
