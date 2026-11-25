"""数据库会话与建表。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回全局 session 工厂（bootstrap 等不走请求依赖的地方用）。"""
    return SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """建新表 + 为存量表自动补齐缺失列（幂等，见 app/migrations.py）。"""
    from .migrations import ensure_columns

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_columns(conn, engine)
