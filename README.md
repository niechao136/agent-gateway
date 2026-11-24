# agent-gateway

基于 **Hermes Agent** 的多 Agent 管理平台。一个平台 Agent = 一个独立的 Hermes profile；平台负责多租户、权限、配置编排与路由，Hermes 负责 LLM 推理、工具执行、Skill 与会话。

> 面向 AI/开发者的入口与红线见 [AGENTS.md](AGENTS.md)；当前状态见 [docs/STATUS.md](docs/STATUS.md)；架构见 [docs/architecture.md](docs/architecture.md)。

## 功能一览

- **Agent 管理**：创建/发布/人格(SOUL)/模型模板；每个 Agent 独立 profile、会话、工具集。
- **工具集**：按 toolset 整组开关；绑定 A2A/Skill 自动开启所需工具集并禁止误关。
- **MCP 服务**：任意 stdio MCP 接入，五种鉴权方式，Agent 勾选即用。
- **Skill**：自定义 Skill（含 scripts/references/templates 上传）+ 内置 Skill 代理，级联禁用。
- **A2A**：出站端点（支持内部 Agent 互绑）+ 对外 Agent Card 与 JSON-RPC（`message/send`、`message/stream`）。
- **知识库（RAGFlow）**：站点 + 库两层配置；内置 MCP `retrieve` 支持多站点路由与结果聚合。
- **连接器**：Telegram / 飞书 / Slack 长连接，消息→会话，状态 SSE。
- **定时任务**：interval/cron，动作 agent_message/a2a_call，结果可投递到会话/日志/Webhook/连接器/知识库。
- **对外 API**：`AgentAPIKey` + Messages 语义的 `/v1/agents/{slug}/messages`。
- **Web**：Next.js 15 + MUI，亮/暗主题、完整管理后台与对话页。

## 技术栈与容器

| 容器 | 技术 | 作用 |
|---|---|---|
| ag-nginx | nginx | 公网入口，反代 `/api`、`/a2a`、`/` |
| ag-web | Next.js 15 / MUI | 管理后台 + 对话页 |
| ag-control | FastAPI / Python 3.14 / asyncpg | 控制层 |
| ag-postgres | PostgreSQL 16 | 唯一事实来源 |
| ag-hermes | 单容器 s6（gateway 8642 + dashboard 9119） | Agent 运行时 |

## 快速开始

```bash
# 本地后端测试
docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t agent-gateway-control:latest ./control
docker run --rm agent-gateway-control:latest python -m pytest tests/ -q

# 本地前端（Windows；WSL /mnt/d 跑 pnpm 会卡）
cd web && pnpm test && pnpm exec tsc --noEmit && pnpm build

# 生产（srv-01）
cd /github/agent-gateway
docker compose --env-file .env --profile full build
docker compose --env-file .env --profile full up -d --no-build
```

配置、环境变量与详细约定见 [docs/conventions.md](docs/conventions.md)。

## 文档导航

- 入口/红线：[AGENTS.md](AGENTS.md)
- 架构：[docs/architecture.md](docs/architecture.md)
- 事实/规格：[docs/specs/](docs/specs/)
- 当前状态：[docs/STATUS.md](docs/STATUS.md)
- 设计决策：[docs/decisions/](docs/decisions/)
- 变更记录：[docs/changes/](docs/changes/)
