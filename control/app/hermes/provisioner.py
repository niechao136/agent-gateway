"""Profile 编排：Agent 记录 → hermes profile。

职责边界：
- 控制层 `agents` 表存元数据（slug / name / status / owner_id / disabled_toolsets）
- 真正配置在 hermes profile 目录（config.yaml / SOUL.md / skills/）
- 本模块负责两者同步，且**只通过 dashboard API 操作**，不直接写文件
  （直接用文件会绕过 hermes 的锁与 reconcile，容易导致状态不一致）
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import get_settings
from ..models import Agent
from .a2a import profile_config_path
from .client import DashboardClient, DashboardError
from .toolsets import normalize_disabled

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def read_soul(profile: str) -> str:
    """读取 profile 当前生效的 SOUL.md（编辑页回填用）。"""
    root = get_settings().hermes_data_root
    path = Path(root) / "profiles" / profile / "SOUL.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("读取 SOUL.md 失败（%s）：%s", path, exc)
        return ""


def ensure_profile_api_key(profile: str) -> None:
    """为 profile 写入专属 API_SERVER_KEY（multiplex 路由鉴权用）。

    hermes 以 GATEWAY_MULTIPLEX_PROFILES=true 运行，
    `/p/<profile>/api/...` 必须用该 profile `.env` 里的 API_SERVER_KEY。
    这里写入与 gateway.profile_api_key() 相同的确定性值，保证控制层与
    profile 端一致；目录未就绪时降级为警告（下次同步补写）。
    """
    from .gateway import profile_api_key

    settings = get_settings()
    env_path = Path(settings.hermes_data_root) / "profiles" / profile / ".env"
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        key_line = f"API_SERVER_KEY={profile_api_key(profile)}\n"
        existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if "API_SERVER_KEY=" in existing:
            import re as _re
            existing = _re.sub(
                r"^API_SERVER_KEY=.*$", key_line.rstrip(), existing, flags=_re.M
            )
            if not existing.endswith("\n"):
                existing += "\n"
            env_path.write_text(existing, encoding="utf-8")
        else:
            with env_path.open("a", encoding="utf-8") as fh:
                fh.write(key_line)
    except OSError as exc:
        logger.warning("写入 profile %s 的 API_SERVER_KEY 失败: %s", profile, exc)


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


def profile_name_for(owner_id: int, slug: str) -> str:
    """(owner_id, slug) → hermes profile 名。

    v2 命名（SPEC-v2 决策 3）：agent-u{owner_id}-{slug}，
    既隔离命名空间，也避免不同用户的同名 slug 冲突。
    """
    return f"agent-u{owner_id}-{slug}"


async def create_agent_profile(
    agent: Agent,
    *,
    soul: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """创建 hermes profile 并返回 dashboard 的响应。"""
    validate_slug(agent.slug)
    pname = profile_name_for(agent.owner_id, agent.slug)

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

    # 写入 profile 专属 API_SERVER_KEY（multiplex 路由鉴权必需）。
    ensure_profile_api_key(pname)

    # profile 建好后写 disabled_toolsets 到 config.yaml（api_server 预设
    # 默认保留 terminal，必须显式禁 —— SPEC §4.4）。
    # config.yaml 尚未落盘时降级为警告（dashboard 异步建目录有延迟），
    # 下次 PATCH/同步时会补写。
    try:
        apply_disabled_toolsets(agent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 disabled_toolsets 失败（降级为警告）: %s", exc)

    logger.info(
        "已创建 profile %s (agent=%s, served_now=%s)",
        pname,
        agent.slug,
        result.get("served_now"),
    )
    return result


def apply_disabled_toolsets(agent: Agent) -> dict:
    """把 agent.disabled_toolsets 写入 profile 的 config.yaml: agent 段。

    与 A2A/models_cfg 共用「直接读写 config.yaml + 原子写」策略。
    失败（profile 目录还没就绪等）由调用方决定是否算致命。
    """
    import yaml

    from .a2a import _atomic_write

    settings = get_settings()
    path = profile_config_path(
        profile_name_for(agent.owner_id, agent.slug), settings.hermes_data_root
    )
    if not path.is_file():
        raise ProvisionError(f"profile config.yaml 不存在: {path}")

    raw = path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(raw) or {}
    if not isinstance(cfg, dict):
        raise ProvisionError(f"{path} 根节点不是映射")

    disabled = normalize_disabled(agent.disabled_toolsets or [])
    section = cfg.get("agent")
    if not isinstance(section, dict):
        section = {}
    if disabled:
        section["disabled_toolsets"] = disabled
    else:
        section.pop("disabled_toolsets", None)
    if section:
        cfg["agent"] = section
    else:
        cfg.pop("agent", None)

    # curator（技能策展器）默认关闭：它会在后台把成功经验自动沉淀为技能，
    # 与平台下发的自定义 Skill 产生同名/同义冲突（如 weather-query）。
    # 需要自动学习时在 .env 里把 CURATOR_ENABLED 设为 true。
    curator = cfg.get("curator")
    if not isinstance(curator, dict):
        curator = {}
    curator["enabled"] = bool(get_settings().curator_enabled)
    cfg["curator"] = curator

    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    logger.info("已写入 %s: disabled_toolsets=%s", path, disabled)
    return {"disabled": disabled}


async def sync_agent_profile(
    agent: Agent,
    *,
    soul: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """同步已有 profile（改人格 / 模型 / 描述）。"""
    pname = profile_name_for(agent.owner_id, agent.slug)
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

    # toolset 变更写 config.yaml；文件不存在时降级为警告（同 create 逻辑）
    try:
        apply_disabled_toolsets(agent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 disabled_toolsets 失败（降级为警告）: %s", exc)
    out["disabled_toolsets"] = list(agent.disabled_toolsets or [])

    return out


async def delete_agent_profile(agent: Agent) -> None:
    pname = profile_name_for(agent.owner_id, agent.slug)
    async with DashboardClient() as client:
        if (await client.get_profile(pname)) is None:
            logger.warning("profile %s 不存在，跳过删除", pname)
            return
        await client.delete_profile(pname)


async def profile_status(owner_id: int, slug: str) -> dict | None:
    """查询某 Agent 对应 profile 的实时状态。"""
    async with DashboardClient() as client:
        return await client.get_profile(profile_name_for(owner_id, slug))


def _default_soul(agent: Agent) -> str:
    return (
        f"你是「{agent.name}」。\n\n"
        f"{agent.description or '请根据用户的问题提供有帮助的回答。'}\n\n"
        "回答要简洁、准确。不确定的事情明确说明，不要编造。"
    )
