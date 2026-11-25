# STATUS.md — 当前状态（只写现状）

更新：2026-11-25 · 环境配置统一（INTERNET_MODE 两档 / 单一 compose / 固定 Hermes 镜像 / 自动权限脚本）

## 总体

- 生产运行正常，5 个容器健康：ag-nginx / ag-web / ag-control / ag-hermes / ag-postgres。
- 对外地址：`http://43.156.187.79:10100`；代码 `/github/agent-gateway`；npm/后端分支 master。
- 本地 = GitHub = 服务器代码一致（`4140ac3`）；工作区干净。
- 测试：后端 **220 passed, 1 skipped**；前端 **17 passed** + tsc 零错误 + next build 成功。

## 已实现能力（按层）

| 能力 | 状态 | 入口 / 事实 |
|---|---|---|
| 用户/角色/归属权限 | 完成 | JWT(sub/role)、`can_modify`、引导管理员、禁止改自己权限 |
| Agent 编排 | 完成 | profile 名 `agent-u{uid}-{slug}`、发布/取消、SOUL 回显、按站点分组的知识库绑定 |
| 统一登录 + 修改密码 | 完成 | 单入口 `/api/auth/*`；改密后清会话 |
| 模型模板 | 完成 | CRUD + 测试端点 + 已应用模型回显（`effective-model`） |
| MCP | 完成 | 独立表 + 五方式鉴权 + Agent 绑定 + 变更即同步 + 连通测试 |
| Skill | 完成 | 自定义 CRUD（references/scripts/templates 上传）+ 内置只读代理 + 级联禁用 |
| A2A | 完成 | 出站端点（五方式鉴权、内部 Agent 互绑、测试、禁自绑）+ **对外 A2A 服务端**（Agent Card + JSON-RPC message/send|stream）+ 入站只读状态 |
| 知识库（RAGFlow） | 完成 | **站点 + 库两层**；多站点 base64 下发；内置 MCP `retrieve` 按 dataset→站点路由、聚合、site_errors；key 掩码；Agent 按站点勾选 |
| 对外 API | 完成 | `AgentAPIKey` + `/v1/agents/{slug}/messages`（Messages 语义，非 OpenAI 兼容）+ 限流 |
| 连接器 | 完成 | Telegram（轮询）/ 飞书（WS）/ Slack（Socket Mode）；长连接、状态 SSE、会话连续；飞书收发已验证 |
| 定时任务 | 完成 | interval/cron；动作 agent_message / a2a_call；结果处理 5 种可多选（会话/日志/Webhook/连接器/知识库） |
| 前端 | 完成 | ThemeRegistry 亮暗、AdminShell、全部管理页、对话页、favicon、HTTP 复制回退 |

## 当前数据量（生产，2026-11-24）

- Agent：3（map / weather / person），person 通过 A2A 绑定另外两个，已验证自动调用。
- RAGFlow：外部自建 `http://139.224.13.57`，3 个数据集（技术 FAQ / 产品手册 / 公司制度）；平台站点/库记录在验证后已清空，待正式配置。
- 飞书连接器：1 个，WS 已连、收发已验证。

## 部署配置（2026-11-25 统一）

- **单一入口**：`make bootstrap/up/build`（内部自动跑 `scripts/fix-data-perms.sh` 建目录+修权限）。`docker-compose.override.yml` 已删除。
- **环境差异只靠 `.env`**：`INTERNET_MODE=direct|cn` 自动派生镜像源（官方 / 清华+npmmirror，可用 `PIP_INDEX_URL`/`NPM_REGISTRY` 覆盖）；`DATA_DIR`/`DATA_UID`/`DATA_GID` 统一路径与属主；`*_MEM_LIMIT` 控制内存；`TUNNEL_ENABLED` 控制隧道。
- **Hermes 镜像固定** `v0.23.2`（= 生产已验证 digest `sha256:d6746a08...`），`HERMES_IMAGE` 可覆盖，不再随 `:latest` 漂移。
- **`.gitattributes`** 锁定 `*.sh`/`scripts/*`/`*.yml` 为 LF，防 Windows CRLF。
- 模板：`.env.example`（分组注释，无需迁移脚本）。

## 已知约束 / 待办

- **RAGFlow Cloud 免费套餐不能用 API Key**（`cloud.ragflow.io` 报需升级 Starter/Pro）；当前使用自建服务。
- 定时任务执行摘要（summary）当前为空（Agent 回复异步生成，日志 delivery 不捕获文本）；如需在历史里看到回复内容，需改 `run_task` 同步等待。
- 服务器本地测试偶发被 60s watchdog / OOM 打断；用后台 job + 日志确认结果。
- 用户工作方式：每阶段先说明思路 → 实施 → 测试 → 用户确认后进入下一阶段；改动即提交。

## 文档

- 事实/spec：[docs/specs/](specs/) · 决策：[docs/decisions/](decisions/) · 变更：[docs/changes/](changes/)
- 架构：[docs/architecture.md](architecture.md) · 约定：[docs/conventions.md](conventions.md) · 入口：[AGENTS.md](../AGENTS.md)
