"""应用入口。

v2 路由挂载（SPEC-v2 批次 1）：
- /api/agents、/api/models、/api/a2a/inbound —— 登录即可，写操作校验归属
- /api/admin/users —— 仅管理员
- /api/chat、/api/chat/agents —— 登录即可
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from .config import get_settings
from .database import get_session_factory, init_models
from .models import User, UserRole
from .routes import (
    a2a as a2a_routes,
    a2a_inbound,
    agents,
    api_keys,
    auth,
    chat,
    connectors as connector_routes,
    mcp as mcp_routes,
    models as model_routes,
    skills as skill_routes,
    toolsets as toolset_routes,
    users,
    v1 as v1_routes,
)
from .scheduler import CleanupTask
from .security import hash_password

logger = logging.getLogger(__name__)

_settings = get_settings()
_cleanup = CleanupTask()


async def _bootstrap_admin() -> None:
    """引导管理员（SPEC-v2 决策 1）。

    启动时若 users 表无任何 role=admin：
    - ADMIN_USERNAME 对应用户已存在（role=user）→ 提权为 admin
    - 否则创建新账号
    数据是丢弃重建的，不存在存量提权遗留问题。
    """
    factory = get_session_factory()
    async with factory() as session:
        admin_count = (
            await session.execute(
                select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
            )
        ).scalar_one()
        if admin_count > 0:
            return

        username = _settings.admin_username
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is not None:
            user.role = UserRole.ADMIN
            logger.info("引导管理员：已将已有用户 %s 提权为 admin", username)
        else:
            user = User(
                username=username,
                password_hash=hash_password(_settings.admin_password),
                display_name="Administrator",
                role=UserRole.ADMIN,
            )
            session.add(user)
            logger.info("引导管理员：已创建 admin 账号 %s", username)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    await _bootstrap_admin()
    _cleanup.start()
    # 连接器：拉起全部 enabled（Telegram/飞书/Slack 长连接）
    from .connectors.base import registry

    started = await registry.start_all()
    if started:
        logger.info("已启动 %d 个连接器", started)
    try:
        yield
    finally:
        await registry.stop_all()
        await _cleanup.stop()


app = FastAPI(title="agent-gateway control", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)          # /api/agents
app.include_router(agents.chat_router)     # /api/chat/agents
app.include_router(mcp_routes.router)      # /api/mcp
app.include_router(mcp_routes.agent_router)  # /api/agents/{id}/mcp
app.include_router(a2a_routes.router)      # /api/a2a/endpoints
app.include_router(a2a_routes.agent_router)  # /api/agents/{id}/a2a
app.include_router(skill_routes.router)    # /api/skills
app.include_router(skill_routes.agent_router)  # /api/agents/{id}/skills
app.include_router(toolset_routes.router)  # /api/toolsets
app.include_router(api_keys.router)        # /api/agents/{id}/api-keys
app.include_router(v1_routes.router)       # /api/v1（对外，agk 鉴权）
app.include_router(connector_routes.router)  # /api/connectors
app.include_router(model_routes.router)    # /api/models
app.include_router(a2a_inbound.router)     # /api/a2a/inbound
app.include_router(users.router)           # /api/admin/users
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-gateway-control", "version": "0.2.0"}
