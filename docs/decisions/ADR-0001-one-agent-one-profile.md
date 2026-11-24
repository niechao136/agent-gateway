# ADR-0001：一个平台 Agent = 一个 Hermes profile

- 状态：Accepted（Batch 1）
- 相关：[架构](../architecture.md)

## 背景
多租户多 Agent，每个 Agent 需要独立模型、人格、工具、Skill、MCP、会话。Hermes 原生支持 profile（独立目录）。

## 决策
平台 Agent 与 Hermes profile 一一对应：`agent-u{owner_id}-{slug}`。profile 目录含 `config.yaml` / `SOUL.md` / `.env` / `skills/` / `state.db` / `cron/` / `memories/`。控制层是「配置编译器 + 路由网关」，Hermes 是执行引擎。

## 后果
- 优点：天然隔离；Hermes 原生 `hermes -p <profile>` 可用；Skill/会话互不干扰。
- 代价：控制层必须正确路由（`/p/{profile}/...` + profile 专属 key），否则走 default profile 报「not connected to any AI provider」——实测踩过。
