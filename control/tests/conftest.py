"""全局测试夹具。

所有测试都在**不连接真实 hermes** 的前提下运行：
- DashboardClient 用 FakeDashboard
- GatewayClient 用 FakeGateway

这样 `docker run --rm ag-control:dev python -m pytest` 在没有 hermes 容器时也能全绿。
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ALLOW_REGISTRATION", "true")

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


# ── 共享 fake 实现 ────────────────────────────────────────
class FakeDashboard:
    """内存版 DashboardClient。状态用类级存储（跨实例共享）。"""

    instances: list["FakeDashboard"] = []
    store: dict[str, dict] = {}
    calls: list[tuple[str, str]] = []

    def __init__(self, *a, **kw):
        FakeDashboard.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return None

    async def login(self):
        return None

    async def list_profiles(self):
        return list(FakeDashboard.store.values())

    async def get_profile(self, name):
        return FakeDashboard.store.get(name)

    async def create_profile(
        self, *, name, soul=None, model=None, provider=None, description=None, mcp_servers=None
    ):
        FakeDashboard.calls.append(("create", name))
        FakeDashboard.store[name] = {
            "name": name,
            "path": f"/opt/data/profiles/{name}",
            "gateway_running": True,
            "soul_set": soul is not None,
        }
        return {"ok": True, "name": name, "served_now": True, "soul_set": soul is not None}

    async def update_profile(self, name, **f):
        FakeDashboard.calls.append(("update", name))
        return {"ok": True}

    async def delete_profile(self, name):
        FakeDashboard.calls.append(("delete", name))
        FakeDashboard.store.pop(name, None)
        return {"ok": True}

    async def set_soul(self, name, soul):
        FakeDashboard.calls.append(("soul", name))
        return {"ok": True}

    async def set_model(self, name, model, provider=None):
        FakeDashboard.calls.append(("model", name))
        return {"ok": True}

    async def set_description(self, name, desc):
        FakeDashboard.calls.append(("desc", name))
        return {"ok": True}

    async def auth_providers(self):
        return [{"name": "basic"}]


class FakeGateway:
    """内存版 GatewayClient。"""

    store: dict[str, dict] = {}
    calls: list[tuple[str, str]] = []
    stream_frames: list[bytes] = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return None

    async def create_session(self, session_id, *, title=None, profile=None):
        from app.hermes.gateway import GatewayError

        if session_id in FakeGateway.store:
            raise GatewayError("dup", status=409)
        FakeGateway.store[session_id] = {"id": session_id, "title": title}
        FakeGateway.calls.append(("create", session_id))
        return {"session": FakeGateway.store[session_id]}

    async def list_sessions(self, *, limit=50, offset=0):
        return list(FakeGateway.store.values())

    async def get_session(self, sid):
        return FakeGateway.store.get(sid)

    async def delete_session(self, sid):
        FakeGateway.calls.append(("delete", sid))
        FakeGateway.store.pop(sid, None)

    async def session_messages(self, sid, *, limit=None):
        return [{"role": "user", "content": "hi"}]

    async def chat_stream(self, sid, message):
        for f in FakeGateway.stream_frames:
            yield f

    async def toolsets(self, profile=None):
        return {"toolsets": {}}


@pytest.fixture(autouse=True)
def _patch_hermes(monkeypatch):
    """全局 patch：任何测试都不应真的连 hermes。"""
    FakeDashboard.instances.clear()
    FakeDashboard.store.clear()
    FakeDashboard.calls.clear()
    FakeGateway.store.clear()
    FakeGateway.calls.clear()
    FakeGateway.stream_frames.clear()

    import app.hermes.client as client_mod
    import app.hermes.conversations as conv_mod
    import app.hermes.gateway as gw_mod
    import app.hermes.provisioner as prov_mod
    import app.routes.chat as chat_route

    monkeypatch.setattr(client_mod, "DashboardClient", FakeDashboard)
    monkeypatch.setattr(prov_mod, "DashboardClient", FakeDashboard)
    monkeypatch.setattr(gw_mod, "GatewayClient", FakeGateway)
    monkeypatch.setattr(conv_mod, "GatewayClient", FakeGateway)
    monkeypatch.setattr(chat_route.gw_mod, "GatewayClient", FakeGateway)

    # 同一事务内共享 engine，测试间隔离
    yield


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
