"""Profile 编排：Agent 记录 → hermes profile。

职责边界：
- 控制层 `agents` 表存元数据（slug / name / status / toolset_tier）
- 真正配置在 hermes profile 目录（config.yaml / SOUL.md / skills/）
- 本模块负责两者同步，且**只通过 dashboard API 操作**，不直接写文件
  （直接用文件会绕过 hermes 的锁与 reconcile，容易导致状态不一致）
"""

from __future__ import annotations

import logging
import re

from ..models import Agent
from .client import DashboardClient, DashboardError
from .toolsets import disabled_toolsets_for

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class ProvisionError(RuntimeError):
    pass


def validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ProvisionError(
            "slug 必须以小写字母或数字开头，只含小写字母/数字/连字符，长度 1-63"
        )
    # hermes 内部保留名，避免冲突
    if slug in {"default", "api", "admin", "system"}:
        raise ProvisionError(f"'{slug}' 是保留名，请换一个")


def profile_name_for(slug: str) -> str:
    """slug → hermes profile 名。

    加前缀避免与用户的 default profile 或未来 hermes 内置名冲突。
    """
    return f"agent-{slug}"


async def create_agent_profile(
    agent: Agent,
    *,
    soul: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """创建 hermes profile 并返回 dashboard 的响应。"""
    validate_slug(agent.slug)
    pname = profile_name_for(agent.slug)

    async with DashboardClient() as client:
        existing = await client.get_profile(pname)
        if existing is not None:
            raise ProvisionError(f"profile '{pname}' 已存在")

        try:
            result = await client.create_profile(
                name=pname,
                soul=soul or _default_soul(agent),
                model=model,
                provider=provider,
                description=agent.description or agent.name,
            )
        except DashboardError as exc:
            raise ProvisionError(f"创建 profile 失败: {exc}") from exc

    logger.info(
        "已创建 profile %s (agent=%s, served_now=%s)",
        pname,
        agent.slug,
        result.get("served_now"),
    )
    return result


async def sync_agent_profile(
    agent: Agent,
    *,
    soul: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """同步已有 profile（改人格 / 模型 / 描述）。"""
    pname = profile_name_for(agent.slug)
    out: dict = {}

    async with DashboardClient() as client:
        if (await client.get_profile(pname)) is None:
            raise ProvisionError(f"profile '{pname}' 不存在")

        if soul is not None:
            await client.set_soul(pname, soul)
            out["soul_updated"] = True

        if model:
            await client.set_model(pname, model, provider)
            out["model_updated"] = True

        if agent.description:
            await client.set_description(pname, agent.description)
            out["description_updated"] = True

        # toolset_tier 变更需要写 config.yaml，当前 dashboard 无对应端点，
        # 走 CLI exec（见 docs/SPEC §4.4 的说明）
        out["disabled_toolsets"] = list(disabled_toolsets_for(agent.toolset_tier))

    return out


async def delete_agent_profile(agent: Agent) -> None:
    pname = profile_name_for(agent.slug)
    async with DashboardClient() as client:
        if (await client.get_profile(pname)) is None:
            logger.warning("profile %s 不存在，跳过删除", pname)
            return
        await client.delete_profile(pname)


async def profile_status(slug: str) -> dict | None:
    """查询某 Agent 对应 profile 的实时状态。"""
    async with DashboardClient() as client:
        return await client.get_profile(profile_name_for(slug))


def _default_soul(agent: Agent) -> str:
    return (
        f"你是「{agent.name}」。\n\n"
        f"{agent.description or '请根据用户的问题提供有帮助的回答。'}\n\n"
        "回答要简洁、准确。不确定的事情明确说明，不要编造。"
    )
