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

## 快速开始（所有环境统一）

所有环境只用一条命令启动，差异全部来自 `.env` 的少数配置项。

```bash
# 1. 生成配置
cp .env.example .env

# 2. 只改这几项（见 .env.example 分组注释）：
#    INTERNET_MODE  — direct(外网直连) / cn(国内，自动用清华PyPI+npmmirror)
#    DATA_DIR       — 数据目录，必须 ext4，绝不能放 /mnt/d
#    DATA_UID/GID   — 数据目录属主，control 与 hermes 共用
#    密钥组          — API_SERVER_KEY / JWT_SECRET / POSTGRES_PASSWORD /
#                     ADMIN_PASSWORD / DASHBOARD_*
#    GATEWAY_PORT / PUBLIC_BASE_URL

# 3. 一键启动（make 会自动建目录、修权限、按网络模式选镜像源）
make bootstrap        # 首次：build + up
# 之后：
make up               # 启动（不重建）
make build            # 改代码后重建镜像
make logs             # 跟踪日志
make test             # 后端测试
```

**镜像源自动派生**：`INTERNET_MODE=direct` → 官方源；`cn` → 清华 PyPI + npmmirror。需要覆盖时在 `.env` 里显式设置 `PIP_INDEX_URL` / `NPM_REGISTRY`（用户值优先）。

**隧道**：仅 `cn` 且需要 Gemini 中转时，把 ssh 私钥放到 `${DATA_DIR}/hermes/.ssh_tunnel_key` 即自动启用；`TUNNEL_ENABLED=0` 或无私钥时安全跳过。`direct` 默认关闭。

**Hermes 镜像已固定**为 `v0.23.2`（生产验证版本，digest 见 compose 注释），不会随 `:latest` 漂移；升级改 `HERMES_IMAGE` 一处即可。

> `docker-compose.override.yml` 已删除。原先服务器专用 uid/gid(1002:1003)、内存限制并入主 compose，由 `DATA_UID/GID`、`*_MEM_LIMIT` 控制。

配置、环境变量与详细约定见 [docs/conventions.md](docs/conventions.md)；环境变量逐项说明见 [.env.example](.env.example)。

## 文档导航

- 入口/红线：[AGENTS.md](AGENTS.md)
- 架构：[docs/architecture.md](docs/architecture.md)
- 事实/规格：[docs/specs/](docs/specs/)
- 当前状态：[docs/STATUS.md](docs/STATUS.md)
- 设计决策：[docs/decisions/](docs/decisions/)
- 变更记录：[docs/changes/](docs/changes/)
