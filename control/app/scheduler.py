"""后台定时任务：软删会话的硬删清理。

背景（SPEC §12.1 决策 4）：
用户删除会话时只做软删（标记 deleted_at），hermes 侧数据保留，
给「误删恢复」留窗口。超过保留期后必须硬删，否则 hermes 的 state.db
会无限增长（SQLite 单文件，VACUUM 需要停机）。

本模块在应用启动时挂一个 asyncio 周期任务，每天跑一次。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .database import SessionLocal
from .hermes.conversations import hard_delete_expired

logger = logging.getLogger(__name__)

# 首次执行延迟：给应用启动留出时间，避免和建表/迁移抢资源
_INITIAL_DELAY_SECONDS = 60
# 之后每天一次
_INTERVAL_SECONDS = 24 * 60 * 60


async def _run_once() -> int:
    async with SessionLocal() as session:
        try:
            n = await hard_delete_expired(session)
            if n:
                logger.info("清理了 %d 个过期软删会话", n)
            return n
        except Exception:  # noqa: BLE001
            logger.exception("清理过期会话失败")
            await session.rollback()
            return 0


async def cleanup_loop(stop: asyncio.Event) -> None:
    """周期清理循环，stop 被 set 时退出。"""
    try:
        await asyncio.wait_for(stop.wait(), timeout=_INITIAL_DELAY_SECONDS)
        return  # 启动后立即收到停止信号
    except TimeoutError:
        pass

    while not stop.is_set():
        await _run_once()
        try:
            await asyncio.wait_for(stop.wait(), timeout=_INTERVAL_SECONDS)
        except TimeoutError:
            continue


class CleanupTask:
    """持有后台任务句柄，便于应用关闭时优雅停止。"""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(cleanup_loop(self._stop), name="conversation-cleanup")
        logger.info("会话清理任务已启动（保留期 %s 天）", _retention_days())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None
        logger.info("会话清理任务已停止")


def _retention_days() -> int:
    from .config import get_settings

    return get_settings().soft_delete_retention_days
