"""Skill 与 A2A 的 profile 级配置。

这两者 hermes 都没有直接的"写入"端点，需要走不同的路径：

**Skill**（dashboard API 支持）：
    GET  /api/skills?profile=<p>        列出（含 39 个内置技能）
    PUT  /api/skills/toggle             启用/禁用
    ★ 注意：hermes 的 skill 是**按 profile 隔离**的开关，
      不是"复制文件"。启用后该 profile 的 sessions 能看到它。

**A2A**（需要写 config.yaml，无 API）：
    a2a_agents 只能通过 config.yaml 配置。
    控制层通过 docker exec 调 `hermes config set` 或在 profile 目录写文件。
    ⚠️ 当前实现只做读取展示，写入留待后续（见 SPEC §7）。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from .client import DashboardClient, DashboardError

logger = logging.getLogger(__name__)


class SkillError(RuntimeError):
    pass


async def list_skills(profile: str) -> list[dict]:
    """列出某 profile 可见的 skills（含 enabled 状态）。"""
    async with DashboardClient() as client:
        try:
            data = await client._request("GET", f"/api/skills?profile={profile}")
        except DashboardError as exc:
            raise SkillError(f"读取 skills 失败: {exc}") from exc

    # 实测返回是裸 list
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("skills", [])
    return []


async def read_skill(profile: str, name: str) -> dict:
    """读取某 profile 下单个 skill 的详情（含 SKILL.md 正文）。

    先取列表拿到元数据，再按 name 请求详情；不同版本 dashboard 的详情
    端点可能不存在，此时回退为仅元数据（content 为空）。
    """
    meta: dict = {}
    for s in await list_skills(profile):
        if (s.get("name") or "") == name:
            meta = dict(s)
            break
    if not meta:
        raise SkillError(f"技能不存在: {name}")

    # Hermes dashboard 的技能正文端点：GET /api/skills/content?name=&profile=
    for path in (
        f"/api/skills/content?name={quote(name)}&profile={profile}",
        f"/api/skills/{quote(name)}?profile={profile}",
    ):
        try:
            async with DashboardClient() as client:
                data = await client._request("GET", path)
        except DashboardError:
            continue
        if isinstance(data, dict):
            content = data.get("content") or data.get("body") or data.get("skill_md")
            if content:
                meta["content"] = content
                if data.get("path"):
                    meta["path"] = data["path"]
                break
    meta.setdefault("content", "")
    return meta


async def toggle_skill(profile: str, name: str, enabled: bool) -> dict:
    """启用/禁用某 profile 的一个 skill。"""
    async with DashboardClient() as client:
        try:
            return await client._request(
                "PUT",
                "/api/skills/toggle",
                json={"name": name, "enabled": enabled, "profile": profile},
            )
        except DashboardError as exc:
            raise SkillError(f"切换 skill 失败: {exc}") from exc


async def set_skills(profile: str, enabled_names: list[str]) -> dict[str, Any]:
    """把某 profile 的 skills 设为指定集合（其余禁用）。

    注意：逐个 toggle 会产生多次请求；内置技能 39 个，
    首次调用约 39 次请求，可接受但不适合高频调用。
    """
    current = await list_skills(profile)
    want = set(enabled_names)
    changed = 0

    for s in current:
        name = s.get("name")
        if not name:
            continue
        should = name in want
        if bool(s.get("enabled")) != should:
            await toggle_skill(profile, name, should)
            changed += 1

    logger.info("profile %s 的 skills 同步完成，变更 %d 项", profile, changed)
    return {"changed": changed, "total": len(current), "enabled": sorted(want)}
