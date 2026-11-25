"""启动期自动迁移：create_all 建新表 + 为已存在的表补齐缺失列。

设计取舍（非 Alembic）：
- 项目的数据策略是"可丢弃重建"，但开发/测试机常有存量库；create_all 不会 ALTER
  已存在的表，导致新增列后旧库 query 直接报错（踩过 scheduled_tasks.next_run_at、
  knowledge_bases.site_id、model_templates.context_length 的坑）。
- 这里用 SQLAlchemy inspector 对比 models 与真实 DB，仅执行 ADD COLUMN（幂等），
  不删列、不改约束、不做数据迁移 —— 这些仍需人工评估，不在自动范围内。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import AddColumn

from .models import Base

logger = logging.getLogger(__name__)


def missing_columns_sync(sync_conn, table) -> list[str]:
    """返回该表在 DB 中缺失的列（供测试与运行时共用）。"""
    inspector = inspect(sync_conn)
    if not inspector.has_table(table.name):
        return []
    existing = {c["name"] for c in inspector.get_columns(table.name)}
    return [c.name for c in table.columns if c.name not in existing]


async def ensure_columns(conn: AsyncConnection, engine: Engine) -> int:
    """为所有已存在的表补齐缺失列，返回执行的 ALTER 数量。"""
    changed = 0
    for table in Base.metadata.sorted_tables:
        missing = await conn.run_sync(lambda sc, t=table: missing_columns_sync(sc, t))
        if not missing:
            continue
        for col_name in missing:
            column = table.columns[col_name]
            try:
                ddl = str(AddColumn(column).compile(dialect=engine.dialect))
            except Exception as exc:  # pragma: no cover - 方言差异兜底
                logger.warning("跳过补列 %s.%s：无法生成 DDL (%s)", table.name, col_name, exc)
                continue
            try:
                await conn.execute(text(ddl))
                changed += 1
                logger.info("自动补列 %s.%s", table.name, col_name)
            except Exception as exc:
                # 典型：NOT NULL 无 default 加到有数据的表。记录但不阻断启动，
                # 让管理员看到日志后决定如何处理存量数据。
                logger.warning("补列失败 %s.%s：%s", table.name, col_name, exc)
    return changed
