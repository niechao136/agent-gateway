"""应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import init_models
from .routes import agent_a2a, agent_skills, agents, auth, chat, users
from .scheduler import CleanupTask

_settings = get_settings()
_cleanup = CleanupTask()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    _cleanup.start()
    try:
        yield
    finally:
        await _cleanup.stop()


app = FastAPI(title="agent-gateway control", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.admin_router)
app.include_router(agent_skills.router)
app.include_router(agent_a2a.router)
app.include_router(agents.user_router)
app.include_router(users.router)
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "agent-gateway-control", "version": "0.1.0"}
