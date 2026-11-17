# 交接文档 — agent-gateway

> 编写时间：2026-11-17 10:00 (Asia/Shanghai)
> 用途：会话切换交接。描述当前状态、已验证能力、已知缺口与踩过的坑。

---

## 一、项目是什么

基于 **hermes-agent** 的多 Agent 管理平台。核心映射：**一个 Agent = 一个 hermes profile**。

- 用户注册登录后与已发布的 Agent 对话
- 管理员在管理中心创建 Agent、配 Skill / MCP / A2A / 模型
- 对话走 `hermes gateway` 的 `/api/sessions/{id}/chat/stream`，控制层翻译成前端 SSE 契约

技术栈：FastAPI + SQLAlchemy(async) + Next.js 16 + MUI 9 + Postgres 16 + hermes-agent 容器。

---

## 二、代码仓库

| 项 | 值 |
|---|---|
| 本地路径 | `D:\agent\agent-gateway`（WSL 视角 `/mnt/d/agent/agent-gateway`） |
| 远端 | `git@github.com:niechao136/agent-gateway.git` |
| 分支 | `master` |
| 最新提交 | `5e304b4` |
| 提交数 | 21 |
| 工作区 | 干净，与远端同步 |

**规格文档**：`SPEC.md`（约 1200 行，含 18 节 + 大量实测发现，是最重要的参考资料）

---

## 三、生产部署（srv-01 新加坡）

### 访问

- **站点**：http://43.156.187.79:10100
- 管理员：`/login` → 切到「管理员」标签
- 凭据在服务器 `/github/agent-gateway/.env` 里（`ADMIN_USERNAME` / `ADMIN_PASSWORD`）

### 目录

```
/github/agent-gateway/          # 代码（用 devops 用户 git clone）
├── .env                        # 生产配置（含密钥，勿提交）
├── docker-compose.yml
├── docker-compose.override.yml # 服务器专用：移除隧道 + 内存上限
├── DEPLOY.md                   # 部署记录（未提交）
├── data/hermes/                # hermes 状态（profiles / state.db / config.yaml / .env）
├── data/postgres/              # 控制层 DB
└── .build/                     # 构建日志
```

### 服务状态

```
ag-hermes     Up (healthy)   8642 + 9119
ag-control    Up (healthy)   8000
ag-web        Up             3000
ag-postgres   Up (healthy)   5432
ag-nginx      Up             0.0.0.0:10100->80
```

### 与本地开发的关键差异

| 项 | 本地 | 服务器 |
|---|---|---|
| 模型访问 | SSH 隧道 → srv-01:8899 | **直连 `172.17.0.1:8899`** |
| 隧道脚本 | cont-init 自动启动 | **已移除**（override 覆盖 volumes） |
| 端口 | 10099 | **10100** |
| 代码来源 | 本地 D 盘 | `devops` 用户 git clone |

---

## 四、已验证可用（服务器实测）

| 能力 | 验证方式 | 结果 |
|---|---|---|
| 页面 | `/` `/login` `/register` `/admin` | 全部 200 |
| 用户注册 | `POST /api/auth/register` | 201 + JWT |
| 管理员登录 | `POST /api/auth/admin-login` | 200 + admin token |
| 创建 Agent | `POST /api/admin/agents` | 201，profile 已建，`gateway_running: true` |
| 发布 Agent | `POST .../publish` | 200 |
| 会话创建 | `POST /api/chat/conversations` | 201 |
| **真实对话** | SSE 流式 | **返回「我是一个大型语言模型，由 Google 训练。」** |
| 模型连通 | 容器内访问 gemini-proxy | 200 |

---

## 五、功能清单

### 后端（133 项测试全通过）

| 模块 | 端点 |
|---|---|
| 用户体系 | `/api/auth/register` `/login` `/me` `/admin-login` |
| Agent CRUD | `/api/admin/agents*`（含 publish/unpublish） |
| Agent Skills | `/api/admin/agents/{id}/skills*` |
| Agent MCP | `/api/admin/agents/{id}/mcp*` + `/mcp-catalog/all` |
| Agent A2A 出站 | `/api/admin/agents/{id}/a2a*` + `/a2a/effective` |
| 模型模板 | `/api/admin/models*` + `/agents/{id}/apply-model/{tid}` |
| 用户管理 | `/api/admin/users*` |
| A2A 入站状态 | `/api/admin/a2a-inbound` |
| 会话 | `/api/chat/conversations*`（含 stream / messages / restore） |
| 后台任务 | 软删会话清理（启动 60s 后，每 24h） |

### 前端（17 项测试全通过）

```
/                 跳转（有 token → /admin 或 /chat，无 → /login）
/login            登录（用户 / 管理员 双 Tab）
/register         注册
/chat             Agent 选择（仅 published）
/chat/[slug]      对话页（SSE 流式 + 历史恢复 + 会话 Drawer）
/admin            Agent 列表
/admin/agents/[id]/edit   Agent 编辑（基础 + Skill + A2A + MCP + 模型）
/admin/users      用户管理
/admin/models     模型模板
/admin/a2a        A2A 入站状态
```

---

## 六、⚠️ 需要注意的地方

### 1. A2A 入站：服务器上**未启用**

三项配置全缺（实测 `ready: false`）：

```env
A2A_HOST=0.0.0.0
A2A_PORT=9900
A2A_BEARER_TOKEN=<随机值>
A2A_TRUSTED_PEERS=ip:127.0.0.1    # ← 最易漏，漏了 dispatch 被拒
```

写进 `/github/agent-gateway/data/hermes/.env` 后重启 hermes 生效。

**本地开发环境是配好的，服务器没有。**

### 2. `.env` 权限问题（已修复，但会复发）

控制层以 `appuser(1000)` 运行，hermes 的 `.env` 属于 `devops(1002)` 且 `600`，
导致 A2A 入站页面报 `Permission denied`。

**修复**：`sudo chmod 640 data/hermes/.env` + `chgrp 1000`

**复发场景**：hermes 重启时可能重写 `.env` 恢复 600 权限。如果 A2A 页面又报错，重跑上面的命令。

### 3. 模型配置：必须在 config.yaml 内联

```yaml
# /github/agent-gateway/data/hermes/config.yaml
model:
  default: "gemini-2.5-flash"
  provider: "custom"
  base_url: "http://172.17.0.1:8899/v1beta/openai"
  api_key: "AIza..."          # ← 必须在这里
```

**`OPENAI_API_KEY` 环境变量无效**（hermes 有白名单，读不到）。

### 4. `gemini-3.5-flash-lite` 不能用

它不接受 `thinkingConfig` 字段，hermes 会发这个字段 → 400。
**必须用 `gemini-2.5-flash`。**

### 5. hermes session 的 title 必须全局唯一

创建 session 时传 `title` 会因重复返回 `400 invalid_title`。
**代码里已改为不传 title**，标题只在控制层本地生成。

### 6. 服务器内存紧张（3.6G 总，swap 3.9G）

- 可用内存约 1.4G
- **`docker build` 会被 OOM 杀掉**（试过多次）
- 构建前先 `sudo docker builder prune -af`
- 已停：minio / qdrant_db / fnb_agent（省 133MB + swap 400MB）
- 待处理：`dsh --profile superagent`（455MB 宿主机进程）

### 7. 构建镜像源

服务器在新加坡，**用默认源更快**。国内镜像（清华/npmmirror）反而慢：

```sh
# control（不需要 PIP_INDEX_URL）
docker build -t agent-gateway-control:latest ./control

# web（不需要 NPM_REGISTRY）
docker build --build-arg CONTROL_URL=http://ag-control:8000 -t agent-gateway-web:dev ./web
```

本地开发则相反，必须用镜像源（但本地 9p 文件系统装不上 pnpm，只能 Docker 构建）。

### 8. 前端 rewrites 在 build 时固化

`CONTROL_URL` 是**构建参数**，运行时改环境变量无效。
所以 nginx 直接反代 `/api/*`，不依赖 Next.js rewrite。

### 9. 改代码后必须重新构建

`docker compose up` **不会**重建镜像。必须：

```sh
docker compose build && docker compose up -d --no-build
```

---

## 七、常用运维命令

```sh
cd /github/agent-gateway

# 状态
sudo -u devops docker compose --env-file .env --profile full ps

# 更新代码 + 重建
sudo -u devops git pull
sudo -u devops docker compose --env-file .env --profile full build
sudo -u devops docker compose --env-file .env --profile full up -d --no-build

# 单个服务重启
sudo -u devops docker compose --env-file .env restart hermes

# 日志
sudo docker logs -f ag-hermes
sudo docker logs -f ag-control
```

**注意**：`docker compose` 要用 `sudo -u devops`（文件和容器都属于 devops）。

---

## 八、已知缺口（可以继续做）

| # | 项 | 说明 |
|---|---|---|
| 1 | A2A 入站未配 | 服务器上三项配置全缺，见 §6.1 |
| 2 | A2A 入站全局 | 一个 token 服务所有 Agent，无法按 Agent 隔离 |
| 3 | MCP 工具过滤 | 未暴露 `tools.include/exclude`，接大工具集会撑爆上下文 |
| 4 | 无用户自助改密码 | 只有管理员禁用/启用 |
| 5 | 登录用 localStorage | 可考虑改 httpOnly cookie |
| 6 | 无审计日志 | 管理操作没有记录 |

---

## 九、参考文档

| 文件 | 内容 |
|---|---|
| `SPEC.md` | 完整规格 + 全部实测发现（**最该先读**） |
| `DEPLOY.md`（服务器） | 部署记录 |
| `../hermes-on-a2a-feasibility.md`（本地） | hermes 接入可行性论证 |

---

## 十、下一步最可能做的事

如果继续功能调整，建议优先级：

1. **修 A2A 入站配置**（服务器上 5 分钟搞定，本地已有验证过的流程）
2. **MCP 工具过滤 UI**（`tools.include` / `tools.exclude`，防止大 MCP 撑爆上下文）
3. **A2A 入站按 Agent 隔离**（需要在 nginx 层做 key → profile 映射）
4. **登录改 httpOnly cookie**（安全性提升）
