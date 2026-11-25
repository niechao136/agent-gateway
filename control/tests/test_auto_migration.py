"""启动期自动补列：create_all 不 ALTER 已存在表，这里验证幂等补列。"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import ensure_columns, missing_columns_sync
from app.models import Base, User


def test_missing_columns_detected_and_added():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            # 建立旧结构：只有部分列（模拟存量库）
            await conn.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), "
                "password_hash VARCHAR(256), display_name VARCHAR(128), role VARCHAR(16), "
                "created_at VARCHAR(32))"
            ))
            missing = await conn.run_sync(
                lambda sc: missing_columns_sync(sc, User.__table__)
            )
            assert missing, "旧结构应检测出缺失列"
            assert "disabled" in missing or "email" in missing or "last_login_at" in missing
            changed = await ensure_columns(conn, engine)
            # 再跑一次应幂等
            changed2 = await ensure_columns(conn, engine)
            assert changed2 == 0
        await engine.dispose()

    asyncio.run(run())


def test_ensure_columns_noop_on_fresh_schema():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            changed = await ensure_columns(conn, engine)
            assert changed == 0
        await engine.dispose()

    asyncio.run(run())
