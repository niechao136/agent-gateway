"""会话归属：控制层 conversations 表 + hermes session 的映射。

★ 这是**安全核心**（SPEC §5.1）。

hermes 的 `/api/sessions` 列出的是该 profile 下**所有**会话，没有业务用户概念
（实测 `user_id` 恒为 `uid:1000` 或 null）。若直接透传，用户 A 会看到用户 B 的会话。

因此：
- 控制层 conversations 表是**唯一**的归属事实来源
- 任何按 id 的访问都必须先校验 `user_id` 匹配
- 绝不把 hermes 的会话列表直接返回给前端
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Agent, Conversation, User
from .gateway import GatewayClient, GatewayError

logger = logging.getLogger(__name__)
_settings = get_settings()


class ConversationError(RuntimeError):
    pass


class ConversationNotFound(ConversationError):
    """会话不存在或不属于该用户（不区分，避免探测）。"""


def new_session_id(user_id: int, prefix: str = "u") -> str:
    """生成 hermes session id。

    带来源前缀便于运维排查（u=用户会话；v1=对外API；tg/fs/slack=连接器）；
    随机部分防止猜测。
    """
    return f"ag_{prefix}{user_id}_{secrets.token_hex(8)}"


def derive_title(message: str, limit: int = 40) -> str:
    """首条消息截断作为标题（SPEC §12 决策 3，不调 LLM）。"""
    text = " ".join(message.split())
    if not text:
        return "新会话"
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def get_owned_conversation(
    session: AsyncSession,
    *,
    user: User,
    conversation_id: int,
) -> Conversation:
    """按 id 取会话，并强校验归属。

    不区分「不存在」和「不属于你」——统一抛 NotFound，避免枚举探测。
    """
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise ConversationNotFound("会话不存在")
    return conv


async def get_owned_by_hermes_id(
    session: AsyncSession, *, user: User, hermes_session_id: str
) -> Conversation:
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.hermes_session_id == hermes_session_id,
                Conversation.user_id == user.id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise ConversationNotFound("会话不存在")
    return conv


async def create_conversation(
    session: AsyncSession,
    *,
    user: User,
    agent: Agent,
    first_message: str | None = None,
) -> Conversation:
    """为用户 + Agent 创建新会话。

    ⚠️ 关键约束（实测，见 SPEC §11.9.7）：
    hermes 要求 session **title 全局唯一**，重复会返回
    400 `invalid_title`（"Title 'X' is already in use by session Y"）。
    而"你好"这类短消息做标题必然撞车，所以**创建时不要传 title**，
    改用本地生成的可辨识标题，只在控制层展示。

    先建 hermes session，再写控制层记录（失败即整体失败，不留孤儿）。
    """
    sid = new_session_id(user.id)
    title = derive_title(first_message) if first_message else "新会话"

    async with GatewayClient() as gw:
        try:
            # 不传 title：避免全局唯一约束冲突
            await gw.create_session(sid)
        except GatewayError as exc:
            raise ConversationError(f"创建 hermes 会话失败: {exc}") from exc

    conv = Conversation(
        user_id=user.id,
        agent_id=agent.id,
        hermes_session_id=sid,
        title=title,
        last_active_at=datetime.now(UTC),
    )
    session.add(conv)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        # DB 失败 → 回滚 hermes 侧，避免孤儿 session
        try:
            async with GatewayClient() as gw2:
                await gw2.delete_session(sid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("回滚 hermes session %s 失败: %s", sid, exc)
        raise
    await session.refresh(conv)
    return conv


async def create_conversation_for_agent(
    session: AsyncSession,
    *,
    agent: Agent,
    source: str = "v1",
) -> Conversation:
    """为 Agent 创建会话，不关联登录用户（对外 API / 连接器用，批次 3）。

    user_id 存 0 表示系统来源；title 带来源前缀避免与用户会话混淆。
    hermes 侧同样不传 title（全局唯一约束，见 create_conversation 注释）。
    """
    sid = new_session_id(0, prefix=source)

    async with GatewayClient() as gw:
        try:
            await gw.create_session(sid)
        except GatewayError as exc:
            raise ConversationError(f"创建 hermes 会话失败: {exc}") from exc

    conv = Conversation(
        user_id=0,
        agent_id=agent.id,
        hermes_session_id=sid,
        title=f"[{source}] {agent.slug}",
        last_active_at=datetime.now(UTC),
    )
    session.add(conv)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        try:
            async with GatewayClient() as gw2:
                await gw2.delete_session(sid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("回滚 hermes session %s 失败: %s", sid, exc)
        raise
    await session.refresh(conv)
    return conv


async def list_conversations(
    session: AsyncSession,
    *,
    user: User,
    agent_id: int | None = None,
) -> list[Conversation]:
    """列出该用户未删除的会话。"""
    stmt = select(Conversation).where(
        Conversation.user_id == user.id,
        Conversation.deleted_at.is_(None),
    )
    if agent_id is not None:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    stmt = stmt.order_by(Conversation.last_active_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def touch_conversation(session: AsyncSession, conv: Conversation) -> None:
    conv.last_active_at = datetime.now(UTC)
    await session.commit()


async def soft_delete_conversation(session: AsyncSession, conv: Conversation) -> None:
    """软删（SPEC §12 决策 4）：标记 deleted_at，**不**删 hermes 侧。

    硬删由定时任务在保留期后执行，见 hard_delete_expired。
    """
    conv.deleted_at = datetime.now(UTC)
    await session.commit()


async def hard_delete_expired(session: AsyncSession, *, retention_days: int | None = None) -> int:
    """硬删超过保留期的软删会话（连带删 hermes 侧）。

    返回被清理的条数。需要定期调用（cron / 启动时）。
    """
    days = retention_days if retention_days is not None else _settings.soft_delete_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)

    rows = list(
        (
            await session.execute(
                select(Conversation).where(
                    Conversation.deleted_at.is_not(None),
                    Conversation.deleted_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    cleaned = 0
    async with GatewayClient() as gw:
        for conv in rows:
            try:
                await gw.delete_session(conv.hermes_session_id)
            except GatewayError as exc:
                # hermes 侧已不存在也算清理成功
                logger.warning("删除 hermes session %s 失败: %s", conv.hermes_session_id, exc)
            await session.delete(conv)
            cleaned += 1
    await session.commit()
    logger.info("硬删了 %d 个过期会话", cleaned)
    return cleaned


async def restore_conversation(
    session: AsyncSession, *, user: User, conversation_id: int
) -> Conversation:
    """恢复软删的会话（回收站功能的基础）。"""
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise ConversationNotFound("会话不存在")
    conv.deleted_at = None
    await session.commit()
    await session.refresh(conv)
    return conv
