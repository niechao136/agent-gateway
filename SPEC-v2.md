# 规格文档 v2 — 多租户与界面重构

> 编写时间：2026-11-17（已锁稿）
> 基于：agent-gateway `146916c`
> 状态：**规格已确认，可开始实施**

---

## 一、变更总览

| # | 变更 | 影响面 |
|---|---|---|
| 1 | 统一登录，所有用户进管理中心 | 鉴权层 + 路由 + 前端全站 |
| 2 | 多租户：资源归属与权限 | 数据模型 + 全部资源接口 |
| 3 | 接口路径重构（去 admin 前缀） | 全部接口 + 前端调用 |
| 4 | 侧边栏布局 + 亮暗主题 + 样式升级 | 前端整体 |
| 5 | 工具配置改为 toolset 逐个开关 | Agent 表单 + 后端 |
| 6 | Skill 页面（内置只读 + 级联禁用） | 新页面 + 后端 |
| 7 | 连接器（飞书/Slack/Telegram） | 新功能 |
| 8 | 对外 API 密钥（Agent 调用凭据） | 新功能（控制层代理） |

---

## 二、鉴权与角色

### 2.1 统一登录

**废弃** `POST /api/auth/admin-login`，只保留一套：

```
POST /api/auth/register   → 201，默认 role=user
POST /api/auth/login      → 200
GET  /api/auth/me         → 含 role
```

JWT 去掉 `scope`，改为 `role`：

```python
{"sub": username, "role": "user" | "admin", "exp": ...}
```

### 2.2 角色

`users` 表新增 `role` 列（默认 `user`）。

| 角色 | 权限 |
|---|---|
| `user` | 可读**所有**已发布 Agent；只能改/删**自己创建的** Agent / MCP / Skill / 模型 / 连接器 |
| `admin` | 全部资源的读/改/删；可改他人角色 |

### 2.3 初始管理员引导

保留 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`：

- 应用启动时，若 `users` 表无任何 `role=admin`，自动创建该账号
- 之后通过用户管理页给他人提权

### 2.4 依赖

```python
get_current_user()   # 任意登录用户
get_current_admin()  # role == "admin"
can_modify(user, resource) -> bool:
    return user.role == "admin" or resource.owner_id == user.id
```

---

## 三、接口路径重构（决策：选 B）

**从 `/api/admin/*` 改为语义化的 `/api/*`**，`/api/admin/` 只保留用户管理。

| 旧路径 | 新路径 |
|---|---|
| `/api/admin/agents*` | `/api/agents*` |
| `/api/admin/agents/{id}/skills*` | `/api/agents/{id}/skills*` |
| `/api/admin/agents/{id}/mcp*` | `/api/agents/{id}/mcp*` |
| `/api/admin/agents/{id}/a2a*` | `/api/agents/{id}/a2a*` |
| `/api/admin/models*` | `/api/models*` |
| `/api/admin/a2a-inbound` | `/api/a2a/inbound` |
| `/api/admin/users*` | **保持** `/api/admin/users*`（仅管理员） |
| — | 新增 `/api/mcp/*`（MCP 独立 CRUD） |
| — | 新增 `/api/skills/*`（Skill 独立 CRUD） |
| — | 新增 `/api/connectors/*` |
| — | 新增 `/api/agents/{id}/keys*`（对外 API 密钥） |

**语义**：前缀不再表示权限级别，权限由后端按 `role` + `owner_id` 判定。

---

## 四、多租户数据模型

### 4.1 Agent

```python
class Agent(Base):
    slug: Mapped[str]
    owner_id: Mapped[int]              # 新增
    profile_name: Mapped[str]          # agent-u{owner_id}-{slug}
    disabled_toolsets: Mapped[list|None]  # 替代 toolset_tier
    UniqueConstraint("owner_id", "slug")
```

- **slug 允许跨用户重复**
- **profile 名**：`agent-u{owner_id}-{slug}`（全局唯一）
- **已发布 Agent**：所有登录用户可见可用

### 4.2 MCP 服务器（新表，独立管理）

```python
class MCPServer(Base):
    id, owner_id
    name: str                # UniqueConstraint(owner_id, name)
    description: str
    transport: str           # stdio / sse / streamable_http / http
    # ── stdio ──
    command: str
    args: JSON
    env: JSON
    # ── http/sse ──
    url: str
    # ── 鉴权（新增，与 A2A 端点同一套）──
    token: str               # 密钥统一存这里
    auth_type: str           # none / bearer / header / query / basic
    auth_name: str           # header→头名 / query→参数名 / basic→用户名
    enabled: bool

class AgentMCPServer(Base):   # 绑定关系
    agent_id, mcp_server_id    # 联合主键
```

**MCP 鉴权（本次补充）**：原来 MCP 没有鉴权字段，现在与 A2A 端点统一。

| transport | 鉴权方式 |
|---|---|
| `stdio` | 密钥通过**环境变量**注入子进程（`MCP_AUTH_TOKEN` / `MCP_AUTH_TYPE`） |
| `sse` / `http` | `auth_type` 决定放 header 还是 query |

**stdio 的特殊处理**（参照 a2a-gateway `auth_scheme.py::build_stdio_env`）：
stdio 无法携带 HTTP 头，改为注入环境变量供本地进程读取：

```python
env.setdefault("MCP_AUTH_TOKEN", token)
env.setdefault("MCP_AUTH_TYPE", auth_type)
env.setdefault("MCP_AUTH_NAME", auth_name)
```

### 4.2.1 MCP 与模型的两种来源

**需求**：既要能从公共列表选，也要能为单个 Agent 单独新增。

| 场景 | 实现 |
|---|---|
| 从列表选 | Agent 绑定已有的 `MCPServer` / `ModelTemplate` |
| 单独新增 | 创建时 `owner_id = 当前用户`，并自动绑定到该 Agent；不勾选"共享给其他 Agent"则仅本人可见可用 |

**UI 表现**：Agent 编辑页的 MCP / 模型选择器里，下拉列表底部有「+ 新建并绑定」选项，弹出内联表单。

**归属规则**：
- 单独新增的资源 `owner_id = 创建者`
- 默认 `is_shared = false`（仅创建者可绑定）
- 可勾选「共享」，则其他用户也能绑定使用（但仍只能创建者/管理员修改）

```python
class MCPServer(Base):
    ...
    is_shared: Mapped[bool] = mapped_column(default=False)
```

模型模板同理加 `is_shared`。

### 4.3 模型模板

现有 `model_templates` 补 `owner_id`。

### 4.4 Skill（两种来源）

| 来源 | 存储 | 可编辑 |
|---|---|---|
| 内置（hermes bundled） | hermes 提供，控制层只读代理 | ❌ 只能全局启停 |
| 自定义（用户上传） | 控制层 `skills` 表 + owner_id | ✅ 本人/管理员 |

```python
class Skill(Base):
    id, owner_id, name, description, content, files(JSON), enabled
    UniqueConstraint("owner_id", name)
```

### 4.5 对外 API 密钥（新表）

**用途**：外部系统调用本平台的 Agent 时用于鉴权（**不是**模型密钥）。

```python
class AgentAPIKey(Base):
    id, agent_id, name, key(unique), is_default, enabled, created_at
    UniqueConstraint("agent_id", "name")
```

- 创建 Agent 时自动生成默认 Key（`is_default=True`，不可删）
- 其余 Key 在 Agent 编辑页按需增删
- Key 格式：`agk_` + 32 hex

### 4.7 A2A 出站端点（新表，独立管理）

**与 MCP 同一模式**：资源独立管理，Agent 只做绑定。

**不在 `.env` 里配**——那是一次性的、改动用不了界面、无法多租户。
参照 `a2a-gateway` 的 `A2AEndpoint` 设计：端点是**可复用的服务定义**，
Agent 侧只做勾选绑定。

```python
class A2AEndpoint(Base):
    id, owner_id
    name: str            # UniqueConstraint(owner_id, name)
    url: str
    description: str
    token: str           # 密钥统一存这里
    auth_type: str       # none / bearer / header / query / basic
    auth_name: str       # header→头名 / query→参数名 / basic→用户名
    capabilities: JSON   # a2a_orchestrate 的路由依据，必填
    timeout: int         # 默认 120
    enabled: bool        # 停用时保留 Agent 上的勾选，重启用即恢复

class AgentA2AEndpoint(Base):   # 绑定关系
    agent_id, endpoint_id        # 联合主键
```

**五鉴权方式**（同 a2a-gateway 的 `auth_scheme.py`）：

| auth_type | 密钥放置位置 | auth_name 含义 |
|---|---|---|
| `none` | — | — |
| `bearer` | `Authorization: Bearer <token>` | 不用 |
| `header` | `<auth_name>: <token>` | 自定义头名 |
| `query` | `?<auth_name>=<token>` | 查询参数名 |
| `basic` | `Authorization: Basic base64(<auth_name>:<token>)` | 用户名 |

**关键设计**：`token` 字段统一承载密钥，`auth_type` 只决定"放哪里"。
这样切换鉴权方式时不用重新填密钥。

**下发**：Agent 保存时，把绑定的端点写入该 profile 的
`config.yaml: a2a_agents.<name>`，包含 url / auth / capabilities / timeout。

**重要**：`capabilities` 必填，它是 `a2a_orchestrate` 按能力路由的依据。为空则该端点无法参与编排。

### 4.8 连接器（新表）

```python
class Connector(Base):
    id, owner_id, name, platform(feishu/slack/telegram), credentials(JSON),
    agent_id(FK, 1:1), enabled, created_at
    UniqueConstraint("owner_id", "name")
```

- 一个连接器绑定一个 Agent
- `credentials` 按平台不同结构，接口返回时**脱敏**

---

## 五、对外 API 网关（控制层代理）

### 5.1 设计原则

**不用 OpenAI 兼容格式。** 原因：

- `chat/completions` 的语义是"调用模型"，而这里是"执行一个 Agent"
- Agent 有 profile / skills / 工具 / 会话状态，不是无状态 completion
- 硬套 `messages` 数组会丢掉"哪个 Agent、哪个会话"这两个关键维度
- 用 `/v1/agents/{slug}/messages` 能自然表达"对某个 Agent 发消息"

**决策**：控制层自己做鉴权，不暴露 hermes 的 API Server。

```
外部系统
  │ Authorization: Bearer agk_xxx
  ▼
控制层 POST /api/v1/agents/{slug}/messages
  │ 1. 查 AgentAPIKey → 定位 Agent
  │ 2. 校验 key.enabled + key.agent_id 匹配 + agent 已发布
  │ 3. session_id 为空则创建会话，否则复用
  │ 4. 转发 hermes /api/sessions/{id}/chat/stream
  ▼
hermes gateway
```

### 5.2 端点

```
POST /api/v1/agents/{slug}/messages     发送消息
GET  /api/v1/agents                    列出该 key 可用的 Agent
GET  /api/v1/sessions/{session_id}     查会话元信息
GET  /api/v1/sessions/{session_id}/messages  拉历史
```

**请求体**：

```json
{
  "content": "你好",
  "session_id": "可选的会话 id，省略则新建",
  "stream": true
}
```

**响应（stream=false）**：

```json
{
  "session_id": "sess_abc123",
  "message": {"role": "assistant", "content": "..."},
  "usage": {"input_tokens": 120, "output_tokens": 45}
}
```

**响应（stream=true）**：SSE，事件与内部对话页一致（`token` / `tool_start` / `tool_end` / `done` / `error`）。

### 5.3 鉴权语义

`AgentAPIKey` 是**按 Agent 隔离**的：

- Key 只能访问它所属的那个 Agent
- `/api/v1/agents` 只返回该 key 对应的 Agent（不是全部）
- 跨 Agent 访问返回 403

**为什么不复用 hermes 的 `API_SERVER_KEY`**：它是全局单 key，无法按 Agent 隔离；且 hermes 的 `/p/<profile>/` 路由的设计目标是内部多 profile，不是对外 API。

### 5.4 限流

按 Key 做简单限流（滑动窗口，内存实现）：

- 默认 60 请求/分钟
- 超限返回 429 + `Retry-After`

### 5.5 端口暴露调整

| 项 | 对外 | 对内 |
|---|---|---|
| hermes 8642 | ❌ 不 publish | ✅ 控制层访问 |
| 控制层 /api/v1/* | ✅ 经 nginx | — |

---

## 六、内置工具配置（toolset 逐个开关）

### 6.1 硬约束（实测）

hermes 内置工具**只能按 toolset 整体开关**：

```sh
$ hermes tools disable web_search
✗ Unknown toolset 'web_search'
```

MCP 工具可以 `server:tool` 逐工具禁用，内置不行。

### 6.2 方案

Agent 表单中**每个 toolset 一个开关**，展开后只读展示内含工具。

`Agent.disabled_toolsets` 存禁用列表，写入 profile 的 config.yaml。

### 6.3 工具清单

控制层内置静态表（来源 `toolsets-reference.md`）：

```python
TOOLSET_CATALOG = {
    "web": {"label": "网页搜索与抓取", "tools": ["web_search","web_extract"], "risk": "low"},
    "browser": {"label": "浏览器自动化", "tools": ["browser_exec","browser_cdp","browser_dialog","browser_vault"], "risk": "critical"},
    "terminal": {"label": "终端与进程", "tools": ["terminal","process_manage"], "risk": "critical"},
    "file": {"label": "文件操作", "tools": ["read_file","write_file","patch","search_files"], "risk": "high"},
    "code_execution": {"label": "代码执行", "tools": ["execute_code"], "risk": "critical"},
    "memory": {"label": "记忆", "tools": ["memory"], "risk": "medium"},
    "skills": {"label": "技能管理", "tools": ["skill_manage","skill_view","skills_list"], "risk": "high"},
    "delegation": {"label": "任务委派", "tools": ["delegate_task"], "risk": "high"},
    "cronjob": {"label": "定时任务", "tools": ["cronjob_manage"], "risk": "high"},
    "computer_use": {"label": "桌面控制", "tools": ["computer_use"], "risk": "critical"},
    "session_search": {"label": "会话搜索", "tools": ["session_search"], "risk": "medium"},
    "vision": {"label": "图像理解", "tools": ["vision_analyze"], "risk": "low"},
    "image_gen": {"label": "图像生成", "tools": ["image_generate"], "risk": "low"},
    "tts": {"label": "语音合成", "tools": ["text_to_speech"], "risk": "low"},
    "todo": {"label": "任务规划", "tools": ["todo_list"], "risk": "low"},
    "clarify": {"label": "澄清提问", "tools": ["clarify"], "risk": "low"},
    "connections": {"label": "连接器管理", "tools": ["manage_connections"], "risk": "medium"},
}
```

### 6.4 UI 规范

- 每行：开关 + 名称 + 风险标签（低危绿/中危黄/高危红）
- 展开：只读展示工具名
- **场景预设**：只读助手（仅 web/vision/clarify）/ 标准（+memory/file）/ 全开
- **高危保护**：`terminal` / `browser` / `code_execution` / `computer_use` 开启时二次确认

---

## 七、Skill 管理

### 7.1 页面结构

```
/admin/skills           自定义 Skill 列表（CRUD）
/admin/skills/builtin   内置 Skill 列表（只读，仅启停）
```

### 7.2 内置 Skill 的启停语义（决策）

**启用**：新增/修改 Agent 时，该 skill **不可见**（不出现可选列表）

**禁用**：
1. 若该 skill 未被任何 Agent 使用 → 直接禁用
2. 若有 Agent 正在使用 → **弹窗列出受影响的 Agent**，用户逐个勾选是否一并禁用
3. 确认后批量执行

**实现**：
- 内置 skill 的全局启停状态存控制层（`builtin_skill_state` 表或复用 `skills` 表加 `is_builtin` 标记）
- Agent 使用某内置 skill = 该 profile 的 `skills/` 目录有对应文件，或在 hermes 侧 toggle 为 enabled
- 禁用时查所有 Agent，列出命中项

### 7.3 接口

```
GET  /api/skills                    自定义 skill 列表
POST /api/skills                    上传
PATCH /api/skills/{id}
DELETE /api/skills/{id}
GET  /api/skills/builtin            内置列表（含 enabled 与使用该 skill 的 Agent）
PUT  /api/skills/builtin/{name}     启用/禁用（body 含 affected_agent_ids）
```

---

## 八、连接器（长连接模式）

### 8.1 核心决策：全部走长连接

**不注册公网域名、不配置加密策略、不暴露 webhook 端点。**

每个平台都有官方的长连接方案，用 SDK 启动客户端即可接收消息：

| 平台 | 机制 | 官方 SDK |
|---|---|---|
| **飞书** | WebSocket 长连接（SDK 内置） | `lark-oapi` |
| **Slack** | Socket Mode（WebSocket） | `slack-bolt` / `slack-sdk` |
| **Telegram** | `getUpdates` 长轮询 | `python-telegram-bot` 或裸 HTTP |

**为什么可行**（[飞书官方文档](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case)）：
> 长连接是飞书 SDK 内提供的能力，你可以在本地服务器集成飞书 SDK，与开放平台建立一条 WebSocket 全双工通道（你的服务器需要能够访问公网）。后续当应用订阅的事件发生时，开放平台会通过该通道向你的服务器发送事件消息。

（[Slack Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)）：
> Socket Mode allows your app to use the Events API and interactive features—**without exposing a public HTTP Request URL**.

### 8.2 架构

```
控制层进程内（或独立 worker）
  ├── 飞书 connector   → lark-oapi WebSocket 客户端
  ├── Slack connector  → bolt SocketModeApp
  └── Telegram connector → getUpdates 长轮询循环
        ↓ 收到消息
  → 归一化为统一结构 {platform, chat_id, user_id, text, thread_ref}
  → 定位绑定的 Agent
  → 创建/复用会话 → 调 hermes
  → 用平台 SDK 回发
```

**关键设计**：每个启用的连接器 = 一个后台任务。用 `asyncio.Task` 管理生命周期：

```python
class ConnectorRunner:
    """每个连接器一个长连接任务。"""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    @property
    def status(self) -> Literal["connecting", "connected", "error", "stopped"]
```

### 8.3 各平台实现要点

**飞书**（`lark-oapi`）：

```python
import lark_oapi as lark

client = lark.ws.Client(app_id, app_secret,
                        event_handler=handler,
                        log_level=lark.LogLevel.INFO)
client.start()   # 阻塞，需在独立线程/任务中运行
```

- 只需 `app_id` + `app_secret`
- 需在飞书后台**订阅事件**（`im.message.receive_v1`）
- 不需要配置 Encrypt Key / Verification Token

**Slack**（`slack-bolt`）：

```python
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

handler = AsyncSocketModeHandler(app, app_token)  # xapp-...
await handler.start_async()
```

- 需要 **app-level token**（`xapp-`）而非仅 bot token
- 需在 App 设置里开启 Socket Mode
- 事件通过 WebSocket 推送，无需 Request URL

**Telegram**（长轮询）：

```python
offset = 0
while running:
    updates = await get_updates(bot_token, offset=offset, timeout=30)
    for u in updates:
        offset = u["update_id"] + 1
        await handle(u)
```

- 只需 `bot_token`
- 需先 `deleteWebhook`（否则 getUpdates 会报错）
- `timeout=30` 是长轮询的关键，避免空转

### 8.4 数据模型

```python
class Connector(Base):
    id, owner_id
    name: str                    # UniqueConstraint(owner_id, name)
    platform: str                # feishu / slack / telegram
    agent_id: int                # 1:1 绑定
    credentials: JSON            # 按平台不同结构
    enabled: bool
    # 运行时状态（不持久化到 DB 也可，用内存 + 定期刷）
    status: str                  # stopped / connecting / connected / error
    last_error: str
    last_connected_at: datetime
```

**credentials 结构**：

| 平台 | 字段 |
|---|---|
| 飞书 | `app_id`, `app_secret` |
| Slack | `bot_token` (`xoxb-`), `app_token` (`xapp-`) |
| Telegram | `bot_token` |

### 8.5 接口

```
GET    /api/connectors              列表（含运行时状态）
POST   /api/connectors              新增（自动启动长连接）
PATCH  /api/connectors/{id}         修改（重启长连接）
DELETE /api/connectors/{id}         删除（停止长连接）
POST   /api/connectors/{id}/restart 手动重连
POST   /api/connectors/{id}/test    发测试消息
```

**没有 webhook 端点**——这是长连接方案的核心优势。

### 8.6 前端

`/admin/connectors`：

- 列表：名称 / 平台 / 绑定 Agent / **连接状态**（绿点=connected，红=error，灰=stopped）
- 新增对话框：选平台 → 显示对应凭证字段 → 选绑定 Agent
- 状态实时刷新（轮询 `/api/connectors` 每 5 秒，或 SSE）
- 错误时展示 `last_error`，提供「重连」按钮

### 8.7 风险与缓解

| 风险 | 缓解 |
|---|---|
| 长连接断开 | SDK 自带重连；额外加 watchdog 定期检查 |
| 控制层重启导致断连 | 启动时自动拉起所有 `enabled` 的连接器 |
| 多实例部署导致重复消费 | 单实例部署（当前架构）；若多实例需加分布式锁 |
| 平台限流 | 回发消息加队列 + 退避 |
| 凭证泄露 | credentials 接口返回脱敏 |

---

## 九、A2A 管理页

### 9.1 为什么独立成页

A2A 有两个方向，**配置粒度完全不同**，混在 Agent 编辑页会让人困惑：

| 方向 | 是什么 | 配置位置 | 粒度 |
|---|---|---|---|
| **出站** | 本平台 Agent → 外部 Agent | 每个 Agent 的 `config.yaml: a2a_agents` | 按 Agent |
| **入站** | 外部 Agent → 本平台 | hermes 的 `.env` | **全局** |

如果把入站配置放进 Agent 编辑页，用户会误以为"每个 Agent 能单独配入站"。

### 9.2 页面结构

`/admin/a2a` 单页三块：

```
┌─ 入站状态（全局）──────────────────────┐
│ 三项检查表：token / host / trusted    │
│ Agent Card 预览 + 技能列表            │
│ 探测按钮                              │
└──────────────────────────────────────┘
┌─ 出站端点列表（带 owner 归属）─────────┐
│ 名称 / URL / 鉴权方式 / 能力 / 操作   │
│ 新增 / 编辑 / 删除                    │
└──────────────────────────────────────┘
┌─ 使用说明 ────────────────────────────┐
│ 如何在 Agent 里绑定这些端点            │
└──────────────────────────────────────┘
```

**新增/编辑对话框字段**：

| 字段 | 说明 |
|---|---|
| 名称 | 会成为 config.yaml 的 key |
| URL | `http(s)://...` |
| 描述 | 可选 |
| **鉴权方式** | 下拉：无 / Bearer / 自定义头 / 查询参数 / Basic |
| **密钥** | 根据鉴权方式显示对应提示 |
| **头名/参数名/用户名** | `auth_type=header/query/basic` 时显示 |
| 能力标签 | 逗号分隔，**必填**（编排依据） |
| 超时 | 秒，默认 120 |
| 启用 | 开关 |

**交互细节**：切换鉴权方式时**保留已填密钥**（只换放置位置）。

### 9.3 接口

```
GET    /api/a2a/endpoints              出站端点列表（本人 + 管理员全部）
POST   /api/a2a/endpoints
PATCH  /api/a2a/endpoints/{id}
DELETE /api/a2a/endpoints/{id}
GET    /api/a2a/inbound                入站状态（全局，只读）
POST   /api/a2a/inbound/ping           探测
```

**Agent 侧绑定**：

```
GET  /api/agents/{id}/a2a              该 Agent 绑定的端点
PUT  /api/agents/{id}/a2a              设置绑定关系（端点 id 列表）
```

---

## 十、前端重构

### 10.1 路由

```
/                      → /admin
/login /register
/admin                  Agent 列表
/admin/agents/new
/admin/agents/[id]/edit
/admin/mcp              MCP 服务器
/admin/skills           自定义 Skill
/admin/skills/builtin   内置 Skill
/admin/models           模型模板
/admin/connectors       连接器
/admin/a2a              A2A（入站状态 + 出站端点）
/admin/api-keys         对外 API 密钥总览
/admin/users            用户管理（仅 admin）
/chat                   Agent 选择（测试用）
/chat/[slug]            对话测试
```

### 10.2 侧边栏

对标 `a2a-gateway/web/src/components/admin/AdminShell.tsx`：

- 固定左侧 Drawer（240px），移动端折叠
- 顶部栏：标题 + 主题切换 + 用户菜单（用户名 + 角色徽章）
- 菜单顺序：**Agent / MCP / Skill / 模型 / 连接器 / A2A / API 密钥 / 用户(admin)**

图标：Agent `SmartToyOutlined`、MCP `ExtensionOutlined`、Skill `AutoStoriesOutlined`、
模型 `MemoryOutlined`、连接器 `CableOutlined`、A2A `HubOutlined`、
密钥 `KeyOutlined`、用户 `AdminPanelSettingsOutlined`

### 10.3 主题系统

参照 `a2a-gateway/web/src/components/ThemeRegistry.tsx`：

- `ColorModeContext`：`mode` / `toggle` / `setMode`
- 存 localStorage，首次读 `prefers-color-scheme`
- 挂载后应用，避免 SSR 水合不一致
- 两套 palette（light / dark）

### 10.4 样式升级

1. 统一圆角 `borderRadius: 12`
2. 列表卡片化（Card 替代裸 Table）
3. 空状态：图标 + 说明 + 主操作
4. 加载态：Skeleton 替代转圈
5. 响应式：移动端侧边栏抽屉化、表格转卡片
6. 深色主题对比度校验

---

## 十一、实施顺序

### 批次 1：后端多租户 + 路径重构
1. `users.role` + 统一登录 + 引导管理员
2. `agents.owner_id` + profile 命名
3. 归属权限校验
4. 接口路径迁移

### 批次 2：资源重构
5. MCP 独立表（含五方式鉴权）+ 绑定关系 + `is_shared`
6. 模型模板 `owner_id` + `is_shared`
7. Skill（自定义 + 内置代理 + 级联禁用）
8. A2A 端点独立表（五方式鉴权）
9. toolset catalog

### 批次 3：新功能
10. 对外 API 密钥 + `/api/v1/agents/{slug}/messages` 代理
11. **连接器长连接**（飞书 `lark-oapi` / Slack Socket Mode / Telegram 长轮询）
    - 先做 Telegram（最简单，纯 HTTP 长轮询）
    - 再做飞书（SDK 成熟）
    - 最后 Slack（需 app-level token）

### 批次 4：前端重构
12. ThemeRegistry + 侧边栏
13. 各页面适配
14. Agent 表单 toolset 开关网格
15. MCP / 模型选择器的「+ 新建并绑定」
16. 连接器状态页（含实时状态）
17. 用户管理（角色调整）

---

## 十二、数据迁移

**决策：丢弃现有服务器数据，重新部署。**

本地开发库也建议清空重建（现有 Agent 只有测试数据）。

迁移脚本**不写**。新 schema 直接 `create_all`（或 alembic 首版）。

**服务器操作**：
```sh
cd /github/agent-gateway
sudo -u devops docker compose --profile full down
sudo rm -rf data/hermes/profiles/agent-* data/postgres
sudo -u devops docker compose --profile full up -d
```

---

## 十三、风险清单

| 风险 | 缓解 |
|---|---|
| **接口路径全改导致前端大改** | 一次性改完，不做兼容层 |
| **profile 重命名** | 直接重建，不迁移 |
| **内置 skill 级联禁用影响多 Agent** | 弹窗让用户逐个勾选 |
| **对外 API 代理成为新攻击面** | 严格校验 key + 只允许已发布 Agent + 限流 |
| **连接器 webhook 无鉴权** | 强制签名校验 + 重放防护 |
| **toolset 全开的安全风险** | 高危二次确认 + 默认禁用 |
| **多租户并发写同一 profile** | 保持单容器；写入加锁 |
| **A2A 端点 token 明文存 DB** | 接口返回脱敏（只回 `has_token`），前端不回显 |
| **A2A 能力标签为空导致编排失效** | 保存时校验必填，前端明确提示用途 |
| **MCP 鉴权字段缺失导致连不上** | 五方式统一；stdio 用环境变量注入 |
| **长连接断开无人知** | SDK 重连 + watchdog + 前端状态展示 |
| **控制层重启后连接器不恢复** | 启动时遍历 enabled 连接器自动拉起 |
| **长连接占内存** | 每个连接器约 10-30MB；服务器内存紧张时限制并发连接器数 |

---

## 十四、已确认决策汇总

| # | 决策 |
|---|---|
| 1 | 接口路径去 `admin` 前缀（选 B） |
| 2 | 密钥 = **外部系统调 Agent 的鉴权密钥**，走控制层代理 |
| 3 | 服务器现有数据直接丢弃，重新部署 |
| 4 | 内置 skill 启用→新增时不可见；禁用→弹窗让用户逐个选受影响 Agent |
| 5 | 内置工具 = toolset 逐个开关 + 内含工具只读展示 |
| 6 | MCP/模型存控制层 DB，带 owner_id |
| 7 | slug 允许跨用户重复，profile 名 `agent-u{owner_id}-{slug}` |
| 8 | 连接器（飞书/Slack/Telegram）纳入本版 |
| 9 | **对外 API 用 Messages 语义**（`/v1/agents/{slug}/messages`），不做 OpenAI 兼容 |
| 10 | **A2A 出站端点独立建表**，不进 `.env`，参照 a2a-gateway |
| 11 | **A2A 鉴权完整五方式**：none / bearer / header / query / basic |
| 12 | **A2A 独立成页**（入站状态 + 出站端点） |
| 13 | **MCP 补鉴权**，与 A2A 同一套五方式（stdio 走环境变量注入） |
| 14 | **MCP/模型支持两种来源**：从共享列表选 / 为单 Agent 新建（`is_shared` 控制） |
| 15 | **连接器全部走长连接**，不用 webhook，无需公网域名与加密配置 |
