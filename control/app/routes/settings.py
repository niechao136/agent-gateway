"""系统设置：暴露可安全查看/修改的运行时配置项。

管理员可查看和修改；修改写入挂载的 .env 并即时更新进程内 settings。
部分配置（curator/self_heal）需要重新下发 profile 才对所有 Agent 生效，
接口会返回 affected_profiles 提示调用方。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..database import get_session
from ..models import Agent, UserRole
from ..security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 可在管理界面查看/修改的配置项：(key, 类型, 说明, 是否敏感)
MANAGED: dict[str, tuple[type, str, bool]] = {
    "curator_enabled": (
        bool,
        "Hermes 技能策展器：自动把成功经验沉淀为技能。开启可能与平台自定义 Skill 语义冲突。",
        False,
    ),
    "self_heal_on_start": (
        bool,
        "启动时自动对齐存量 profile（技能目录名/脚本/强制工具集/影子技能）。幂等。",
        False,
    ),
    "allow_registration": (bool, "是否允许用户自助注册。", False),
    "soft_delete_retention_days": (int, "软删除数据保留天数。", False),
}


class SettingItem(BaseModel):
    key: str
    value: Any
    type: str
    description: str


@router.get("", response_model=list[SettingItem])
async def list_settings(_: CurrentUser) -> list[SettingItem]:
    s = get_settings()
    out = []
    for key, (typ, desc, _secret) in MANAGED.items():
        out.append(
            SettingItem(key=key, value=getattr(s, key), type=typ.__name__, description=desc)
        )
    return out


class UpdateIn(BaseModel):
    values: dict[str, Any]


@router.put("")
async def update_settings(
    body: UpdateIn,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅管理员可修改系统设置")

    s = get_settings()
    # 校验
    for key, val in body.values.items():
        if key not in MANAGED:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"未知配置项: {key}")
        typ, _desc, _secret = MANAGED[key]
        if typ is bool:
            if not isinstance(val, bool):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key} 必须是布尔值")
        elif typ is int:
            if not isinstance(val, int) or isinstance(val, bool):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key} 必须是整数")

    # 写 .env（保留其它行）
    env_path = Path(s.hermes_dotenv_path).parent / ".env"
    # 生产实际 .env 在仓库根；hermes_dotenv_path 是 hermes 的 .env。
    # 优先用仓库根 .env（ DATABASE_URL 等所在处），通过 database_url 无法反推，
    # 因此用 CWD/.env 兜底。
    candidates = [Path(".env"), env_path]
    target = next((p for p in candidates if p.is_file()), None)

    if target:
        try:
            text = target.read_text(encoding="utf-8")
            lines = text.splitlines()
            for key, val in body.values.items():
                pattern = re.compile(rf"^{re.escape(key)}=.*$")
                newline = f"{key}={str(val).lower() if isinstance(val, bool) else val}"
                if any(pattern.match(line) for line in lines):
                    lines = [pattern.sub(newline, line) for line in lines]
                else:
                    lines.append(newline)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("写 .env 失败（设置已在进程内生效，重启后会丢失）: %s", exc)

    # 更新进程内 settings
    for key, val in body.values.items():
        setattr(s, key, val)

    affected = 0
    if any(k in body.values for k in ("curator_enabled", "self_heal_on_start")):
        affected = len((await session.execute(select(Agent.id))).scalars().all())

    return {"updated": list(body.values), "affected_profiles": affected}
