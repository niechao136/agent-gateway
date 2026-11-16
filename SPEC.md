# agent-gateway 规格文档

> 基于 hermes-agent 的多 Agent 管理平台。**新仓库从零开始，不迁移旧数据。**
>
> 三项核心决策（本版确定）：
> 1. **直接接入 hermes**，不保留 LangGraph 运行时
> 2. **不考虑旧数据**，无需数据迁移
> 3. **新增用户表 + 注册页**，对话页全部需登录

- 仓库：`D:\agent\agent-gateway`（`master` 分支，无提交）
- 基线参考：`D:\agent\a2a-gateway`（仅作功能参照，不迁移代码逻辑）
- 架构依据：[hermes-on-a2a-feasibility.md](../hermes-on-a2a-feasibility.md)
- 状态：**规格阶段**

---

## 一、系统定位与核心变化

### 1.1 一句话定位

**一个多用户、多 Agent 的 Web 平台**：用户注册登录后，可与管理员配置的 Agent 对话；管理员通过管理中心创建 Agent（= hermes profile）、配置模型/MCP/Skill/A2A。

### 1.2 与 a2a-gateway 的根本差异

| 维度 | a2a-gateway | agent-gateway |
|---|---|---|
| Agent 运行时 | LangGraph（自建图） | **hermes-agent**（profile） |
| Agent 定义 | `agent_configs` 表一行 | **profile 目录**（文件即定义） |
| 会话存储 | Postgres checkpointer | **hermes 的 sessions DB** |
| 用户体系 | 匿名 visitor + 管理员 | **注册用户 + 管理员** |
| 首页 | 默认 Agent 对话页 | **管理中心** |
| 语音 | TTS + ASR | **无** |
| 工具集 | 自建（a2a_call / mcp_call） | **hermes 内置 + 需严格削减** |

### 1.3 不变量

- SSE 对话流的事件契约（`token` / `tool_start` / `tool_end` / `interrupt` / `done` / `error`）——前端可复用
- 管理端的 Agent 表单结构（基本信息 / A2A / MCP / Skill / System Prompt / 模型）
- 连接器（飞书 / Slack / Telegram）功能

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────┐
│  nginx（唯一对外端口）                                │
│    /                → 控制层前端 (Next.js)            │
│    /api/*           → 控制层后端 (FastAPI)            │
│    /p/<slug>/v1/*   → hermes gateway (内部)           │
└─────────────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
┌──────────────────┐   ┌──────────────────────────────┐
│ 控制层 FastAPI    │   │ hermes-gateway (profile 宿主) │
│  - 用户/注册/登录  │   │  - 每个 Agent = 一个 profile  │
│  - Agent 管理      │──▶│  - /p/<slug>/v1/chat/...     │
│  - 会话归属映射    │   │  - /api/profiles (dashboard) │
│  - SSE 翻译代理    │   │  - /api/sessions (会话存储)   │
└──────────────────┘   └──────────────────────────────┘
         │                      │
         ▼                      ▼
┌──────────────────┐   ┌──────────────────────────────┐
│  Postgres         │   │ hermes-dashboard (管理 API)   │
│  users / agents / │   │  /api/profiles /api/skills   │
│  conversations    │   │  /api/mcp /api/model/set     │
└──────────────────┘   └──────────────────────────────┘
```

**关键设计点**：控制层不自己存对话内容，只存**会话归属映射**。真正的消息在 hermes 的 sessions DB 里。

---

## 三、用户体系（新增）

### 3.1 数据模型

新增 `users` 表（与现有 `admin_users` 并存）：

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(64))
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

**与 `admin_users` 的关系**：两套独立表，两套独立 JWT scope。

| 表 | 用途 | JWT claim |
|---|---|---|
| `admin_users` | 管理中心登录 | `scope: "admin"` |
| `users` | 对话页登录 | `scope: "user"` |

**为什么不合并成一张表加 role 字段**：

- 管理员的登录路径（`/login` → `/admin`）与用户登录路径（`/login` → `/chat`）不同
- 管理员账号数量极少（个人项目 1 个），与用户表混在一起会让"删用户"和"删管理员"的语义纠缠
- 两张表的 JWT 密钥可以分开轮换

如果后续觉得麻烦，合并是可行重构，但现在分开更清晰。

### 3.2 密码存储

复用现有 `admin_users` 的哈希方案（`auth.py` 里的 `password_hash` 逻辑）。**不要引入新库**——现有方案已验证可用。

### 3.3 注册页

新增 `web/src/app/register/page.tsx`：

| 字段 | 校验 |
|---|---|
| 用户名 | 3-64 字符，`[a-zA-Z0-9_-]`，唯一 |
| 密码 | 最少 8 字符 |
| 确认密码 | 与密码一致 |
| 邮箱（可选） | 格式校验，唯一 |

**是否开放自助注册**：需要你决策（见 §九）。默认实现为**开放注册**，但加一个配置开关 `settings.allow_registration`，关掉后注册接口返回 403。

### 3.4 鉴权接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 注册，成功即返回 token |
| POST | `/api/auth/login` | 用户登录，返回 user JWT |
| POST | `/api/auth/logout` | 清除 cookie |
| GET | `/api/auth/me` | 当前用户信息 |

管理端保持现状：`POST /api/admin/login`。

### 3.5 鉴权依赖

```python
# deps.py 新增
async def get_current_user(request: Request) -> User:
    """解析 user JWT，校验 scope == "user" """

async def get_current_admin(request: Request) -> AdminUser:
    """现有实现，校验 scope == "admin" """
```

**关键**：两套 JWT 用同一个签名密钥但不同 `scope` claim。`get_current_user` 必须显式拒绝 `scope == "admin"` 的 token，反之亦然——否则管理员 token 能当用户 token 用（虽然危害小，但语义混乱）。

---

## 四、Agent 管理（hermes profile 编排）

### 4.1 Agent 的定义方式

**Agent = hermes profile**。控制层的 `agents` 表只存**元数据和映射**，真正的配置在 profile 目录。

```python
class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    profile_name: Mapped[str] = mapped_column(String(64), unique=True)  # hermes profile 名
    status: Mapped[str] = mapped_column(default="draft")  # draft / published
    toolset_tier: Mapped[str] = mapped_column(default="public")  # public / member / admin
    created_at / updated_at
```

**没有的字段**（相比 a2a-gateway）：

| 废弃字段 | 原因 |
|---|---|
| `system_prompt` | 写入 profile 的 `SOUL.md` |
| `model_id` / `model_snapshot` | 写入 profile 的 `config.yaml` |
| `mcp_server_ids` / `mcp_servers` | 写入 profile 的 `config.yaml: mcp_servers` |
| `skill_ids` / `skills` | 复制到 profile 的 `skills/` 目录 |
| `a2a_targets` / `a2a_target_ids` | 写入 profile 的 `config.yaml: a2a_agents` |

### 4.2 Agent 创建流程

```
管理员填表
   ↓
POST /api/admin/agents
   ↓
控制层调 hermes: POST /api/profiles
   body: { name, soul, model, mcp_servers, hub_skills }
   ↓
hermes 创建 profile 目录并立即开始服务（served_now）
   ↓
控制层写入 agents 表
   ↓
返回 Agent 记录
```

**关键 API**（`hermes_cli/web_routers/profiles.py:747`）：

```
POST /api/profiles
{
  "name": "my-agent",
  "soul": "你是一个...",           # → SOUL.md
  "model": "claude-sonnet-4",
  "provider": "anthropic",
  "mcp_servers": [...],            # → config.yaml
  "hub_skills": [...],             # 异步安装
  "description": "..."
}
→ { path, model_set, model_error, mcp_written, warnings, served_now }
```

**`served_now` 字段很重要**：它表示新 profile 已被运行中的 multiplexer 接管，无需重启。控制层应把这个状态回显到 UI。

### 4.3 Agent 更新流程

```
PATCH /api/profiles/{name}   → 改元数据
PUT   /api/profiles/{name}/soul → 改人格
PUT   /api/model/set?profile=<name> → 改模型
```

**注意**：修改已有 profile 的 `config.yaml` / skills **通常需要重载**（与新建不同）。控制层要处理"生效中"状态，见 §八.3。

### 4.4 工具集分级（安全核心）

`toolset_tier` 决定该 Agent 能用的工具。**不要暴露原始 toolset 列表给用户勾选**。

| tier | 适用 | disabled_toolsets |
|---|---|---|
| `public` | 普通注册用户 | `terminal`, `file`, `browser`, `code_execution`, `computer_use`, `delegation`, `cronjob`, `skills`, `memory` |
| `member` | 信任用户 | 同上，但放开 `memory`, `session_search` |
| `admin` | 管理员测试 | 全开 |

**写入方式**：创建/更新 profile 时，把 `disabled_toolsets` 写进该 profile 的 `config.yaml`：

```yaml
agent:
  disabled_toolsets:
    - terminal
    - file
    - browser
    - code_execution
    - computer_use
    - delegation
    - cronjob
    - skills
    - memory
```

**验证方式**：创建后调 `GET /v1/toolsets`（带该 profile 的 key）核对实际生效结果。**不要只信配置文件**。

⚠️ **`/v1` 用的是 `api_server` 平台预设，它默认保留 terminal**。不显式配置 `disabled_toolsets` 等于给用户一个容器 shell。

### 4.5 模型 / MCP / Skill 的管理

这三者保留"全局模板库"的概念，但**下发方式改变**：

| 资源 | 存储 | 下发方式 |
|---|---|---|
| 模型 | 控制层 `model_templates` 表 | 创建/更新 profile 时写 `config.yaml` |
| MCP | 控制层 `mcp_servers` 表 | 同上，写 `mcp_servers` 块 |
| Skill | 控制层 `skills` 表（含附件） | **复制文件到 profile 的 `skills/` 目录** |

**Skill 的关键点**（详见 §六）：hermes 里"绑定 skill"就是"文件在不在那个目录"，没有勾选动作。

---

## 五、会话与对话

### 5.1 核心难点：hermes 的 session 没有用户归属

这是本规格**最重要的一个设计约束**。

`GET /api/sessions` 列出的是**该 profile 下的所有会话**，没有 `user_id` 概念（`api_server.py:1561`）。而你需要"用户 A 只看到自己的会话"。

**解决方案：控制层维护归属映射。**

```python
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    hermes_session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    created_at / updated_at / last_active_at
```

**工作流**：

```
用户发消息
   ↓
控制层查 conversations（user_id + agent_id + 会话id）
   ↓ 有 → 复用 hermes_session_id
   ↓ 无 → POST /api/sessions 创建，记录到 conversations
   ↓
POST /p/<slug>/api/sessions/{hermes_session_id}/chat/stream
   ↓
把 hermes 的 SSE 翻译成前端契约
```

**会话列表**：

```
GET /api/chat/conversations?agent=<slug>
   ↓
只查控制层 conversations 表（WHERE user_id = current_user.id）
   ↓
可选：对每个 session 调 hermes 取最后消息预览
```

**为什么不直接透传 hermes 的 `/api/sessions`**：因为它不区分用户，透传等于所有用户共享会话列表——**这是严重的越权漏洞**。

### 5.2 hermes 的会话 API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/sessions` | 创建会话（可指定 id） |
| GET | `/api/sessions/{id}/messages` | 读消息（支持 limit/offset/order） |
| POST | `/api/sessions/{id}/chat/stream` | **流式对话**（推荐） |
| POST | `/api/sessions/{id}/chat` | 非流式 |
| DELETE | `/api/sessions/{id}` | 删除 |
| POST | `/api/sessions/{id}/fork` | 分叉 |
| POST | `/api/sessions/{id}/model` | 会话级模型覆盖 |

**`hermes_session_id` 的生成**：建议控制层生成带前缀的 ID，便于识别：

```python
hermes_session_id = f"ag_{user_id}_{uuid4().hex[:16]}"
```

`POST /api/sessions` 支持传入自定义 `id`（`api_server.py` 的 `_handle_create_session`），但会校验路径安全性、长度上限。

### 5.3 为什么用 `/api/sessions/{id}/chat/stream` 而不是 `/v1/chat/completions`

| | `/v1/chat/completions` | `/api/sessions/{id}/chat/stream` |
|---|---|---|
| 会话管理 | 靠 `X-Hermes-Session-Key` header 隐式 | **显式 session id** |
| 历史加载 | 需要 header 保持 | 自动 |
| 与你的 `conversations` 表 | 需要额外映射 | **直接对应** |
| 工具进度事件 | `hermes.tool.progress` | 同类事件 |

**推荐 `/api/sessions/{id}/chat/stream`**：会话 ID 显式，与你的归属表天然对应，避免 header 隐式状态带来的混乱。

### 5.4 SSE 翻译层

hermes 的 SSE → 前端契约的映射：

| hermes 事件 | 前端事件 | 转换 |
|---|---|---|
| 内容增量 chunk | `token` | `{content: delta}` |
| `hermes.tool.progress`（start） | `tool_start` | `{name}` |
| `hermes.tool.progress`（end） | `tool_end` | `{name, output}` |
| 流结束 | `done` | `{thread_id: hermes_session_id}` |
| 错误帧 | `error` | `{detail}` |
| `: keepalive` 注释行 | **跳过** | 前端解析器要能忽略 `:` 开头的行 |

⚠️ **keepalive 行**：hermes 每 10 秒无事件时发 `: keepalive`（`api-server.md:216`）。你的 SSE 解析器**必须跳过注释行**，否则会解析失败。这是最容易踩的坑。

### 5.5 删除会话

```
DELETE /api/chat/conversations/{id}
   ↓
校验归属（user_id 匹配）
   ↓
调 hermes DELETE /api/sessions/{hermes_session_id}
   ↓
删除控制层 conversations 记录
```

**注意**：hermes 删除 session 后会保留 7 天 tombstone（`api-server.md:129`）。如果用户用相同 ID 重建，会命中 tombstone 逻辑。**建议**：删除时一并把 `hermes_session_id` 标记为已删除，不复用。

---

## 六、Skill 处理

### 6.1 定义与下发

| 环节 | 方式 |
|---|---|
| 定义 | 控制层 `skills` 表（name / description / content / files） |
| 下发 | **复制到 `profiles/<name>/skills/<category>/<skill>/`** |
| 绑定 | 文件在该目录 = 已绑定 |
| 解绑 | 删除该目录 |

**没有"勾选"动作**。管理界面的多选框语义是"把选中的 skill 复制过去"。

### 6.2 目录结构

```
profiles/<agent-profile>/skills/
└── <category>/
    └── <skill-name>/
        ├── SKILL.md
        ├── references/
        ├── templates/
        ├── scripts/
        └── assets/
```

### 6.3 引用文件：白名单前移

**hermes 的 `skill_view(name, path)` 没有文件白名单**，能读该 skill 目录下任意文件。

**解决方案**：白名单从"读取时过滤"前移到**写入时过滤**——落盘时就排除不要的文件。这比改 hermes 读取逻辑简单。

### 6.4 可执行代码：没有 `run_skill_script`

hermes **没有** skill 专用的脚本执行工具，脚本靠 `terminal` / `execute_code` 跑。

**影响**：
- `public` tier 禁了 `terminal`，所以**所有带脚本的 skill 都跑不起来**
- 带脚本的 skill 对 public Agent 只能保留 `references/` 文档部分

### 6.5 带脚本 skill 的处理：自动注入 `requires_toolsets`

**问题**：如果只是「不部署 `scripts/`」，会留下断链——`SKILL.md` 里写着「运行 `scripts/foo.py`」，但文件不存在。agent 读不到脚本，通常会兜底按文档手工实现，导致**同一 skill 在不同对话里行为不一致**，且用户会看到莫名其妙的错误。

更糟的情况：很多 skill 的价值主体就是脚本（数据转换、API 封装、批处理），`SKILL.md` 只是「调用 scripts/xxx.py」的说明书。去掉脚本后它不报错，只是**永远无用**，还占着 Level 0 清单的位置和 token。

**解决方案：不靠删文件，靠 hermes 的条件激活机制让它自动隐藏。**

hermes 支持在 `SKILL.md` frontmatter 里声明（`skills.md:283-292`）：

```yaml
metadata:
  hermes:
    requires_toolsets: [terminal]   # 仅当 terminal 可用时才显示该 skill
```

| 字段 | 行为 |
|---|---|
| `requires_toolsets` | 列出的 toolset **不可用**时，skill **隐藏** |
| `requires_tools` | 同上，但按单个工具判断 |
| `fallback_for_toolsets` | 列出的 toolset **可用**时隐藏（用于降级方案） |

**下发逻辑**：

```
读取 skill 的 files 清单
   ↓
判断是否含 scripts/ 目录
   ↓ 不含 → 原样下发，不注入
   ↓ 含   → 剥离 scripts/ 后下发
            + 自动给 SKILL.md 的 frontmatter 补 requires_toolsets: [terminal]
```

**效果**：

| tier | terminal | 结果 |
|---|---|---|
| `public` | 禁用 | skill **自动隐藏**，不进 Level 0 清单，不浪费 token |
| `member` | 禁用 | 同上 |
| `admin` | 启用 | skill 正常出现，脚本可跑（完整下发，不剥离） |

**为什么这样比"只不部署"好**：

| | 只不部署 scripts/ | 注入 requires_toolsets |
|---|---|---|
| public 用户看到的技能清单 | 含一个永远失败的技能 | 干净的、都能用的清单 |
| agent 行为 | 读不到脚本，兜底或报错，不确定 | 技能根本不出现，无歧义 |
| token 开销 | 白占 Level 0 位置 | 不占 |
| 维护成本 | 无 | 下发时多一次 frontmatter 注入 |

**实现要点**：

1. **frontmatter 注入要幂等**：如果 skill 自己已经声明了 `requires_toolsets`，不要覆盖，而是**取并集**（追加 `terminal`）。避免覆盖作者原本的意图。
2. **注入要在落盘前做**，直接改写入 profile 的 `SKILL.md` 内容，不要留到运行时。
3. **只对含 `scripts/` 的 skill 注入**。纯文档 skill 不要加，否则它们会因为 terminal 被禁而在 public 下消失——那是误伤。
4. **`admin` tier 要完整下发**，包括 `scripts/`，且不注入（terminal 可用，无需隐藏）。

**判断"是否含脚本"的依据**：控制层 `skills` 表的 `files` JSONB 里应有路径信息。上传时就能识别出 `scripts/` 前缀的文件，建议在 `skills` 表加一个派生字段：

```python
has_scripts: Mapped[bool] = mapped_column(default=False)  # 由 files 推导
```

这样下发时不用每次都遍历文件列表。

**备选方案（不推荐）**：

| 方案 | 问题 |
|---|---|
| 下发时剥离 `SKILL.md` 里引用 `scripts/` 的段落 | 破坏文档完整性，正则匹配易漏 |
| 拆分 skill（知识 / 自动化两份） | 每个 tier 都有用，但要维护两份 |
| 什么都不做，保持完整下发 | public 下脚本不可执行，且 `skill_view` 能读到脚本内容（信息暴露） |

### 6.6 `load_mode=always` 的迁移

hermes 是严格 progressive disclosure，**没有"正文常驻"开关**。

| 原语义 | 新做法 |
|---|---|
| 短小常驻规则 | 写入 `SOUL.md` |
| 每轮需要的事实 | 写入 MEMORY |
| 长文档常驻 | 无好办法，重新设计 |

---

## 七、A2A 处理

### 7.1 出站（Agent 调外部）

hermes 提供 5 个工具：`a2a_discover` / `a2a_call` / `a2a_list` / `a2a_history` / `a2a_orchestrate`。

配置写入 profile 的 `config.yaml`：

```yaml
a2a_agents:
  researcher:
    url: "http://...:9900"
    auth: { type: bearer, token: "${RESEARCHER_TOKEN}" }
    timeout: 120
    capabilities: [web_search, research]   # ← a2a_orchestrate 的路由依据
```

**`capabilities` 字段必填**，否则 `a2a_orchestrate` 无法路由。

### 7.2 入站（被外部调用）

配置 served agents：

```yaml
gateway:
  platforms:
    a2a:
      enabled: true
      extra:
        host: 0.0.0.0
        port: 9900
        agents:
          alice:
            slug: alice
            profile: alice-profile
            name: "Alice Assistant"
            description: "..."
```

### 7.3 Docker 必配三项（缺一不可）

```yaml
A2A_BEARER_TOKEN: "..."        # 或 A2A_PEER_TOKENS；否则只绑 loopback
A2A_HOST: "0.0.0.0"            # 否则出不了容器
A2A_TRUSTED_PEERS: "..."       # 否则 dispatch 被静默拒绝
```

### 7.4 已知限制

| 项 | 说明 |
|---|---|
| per-Agent API Key | hermes 只有 per-peer / shared token，粒度更粗。如需细粒度，在 nginx 层做 key → profile 映射 |
| `input-required` 闭环 | 无 `a2a_resume`，用 `context_id` 续接；**跨请求的 context_id 要控制层自己存** |
| 入站注入 live session | hermes 会把外部请求混进活跃会话。对外 endpoint 应走 served_agents 指向**专用 profile** |

---

## 八、部署

### 8.1 compose 拓扑

```yaml
services:
  nginx:          # 唯一对外端口
  web:            # Next.js
  control:        # FastAPI 控制层
  postgres:       # 控制层自用
  hermes:         # ★ 单容器：s6 同时监管 gateway(8642) + dashboard(9119)
```

**⚠️ hermes 必须是单个容器，不能拆成 gateway 容器 + dashboard 容器。**

实测：两个容器共享同一个 `/opt/data` 会让两者争抢 `gateway.lock` 和 `state.db`，dashboard 反复崩溃重启（`RestartCount` 持续增长、监听端口随机漂移）。官方设计就是单容器内 s6 监管多个服务。

### 8.1.1 ⚠️ 必须显式设置 `command: ["gateway", "run"]`

这是本次搭建中**最耗时的一个坑**，必须写进 compose：

```yaml
hermes:
  image: nousresearch/hermes-agent:latest
  command: ["gateway", "run"]     # ★ 不可省略
```

**不设置的后果**：镜像的 CMD 走 `docker/main-wrapper.sh`，无参数时执行 `hermes`（交互式 CLI），进程启动后立即退出 → 容器无限重启。实测表现：

| 现象 | 说明 |
|---|---|
| `RestartCount` 持续增长 | 约 50 秒一次 |
| 监听端口随机漂移 | 40617 → 45691 → 43635 … |
| dashboard 反复 `READY` 又消失 | 日志里 `HERMES_DASHBOARD_READY` 反复出现 |
| `errors.log` 反复 `Shutdown context: signal=SIGTERM parent_name=s6-supervise` | 容器关停导致 |
| 容器 `ExitCode=0` | 干净退出，不是崩溃 |

**排查提示**：如果你的 hermes 容器在循环重启但日志看不出错误，先检查 `command` 是否设置。这个坑很隐蔽，因为所有服务日志都是正常的，只有容器在重启-重新初始化。

### 8.2 关键环境变量

| 变量 | 值 | 说明 |
|---|---|---|
| `HERMES_UID` / `HERMES_GID` | 宿主 uid/gid | 否则挂载卷权限错乱 |
| `API_SERVER_ENABLED` | `true` | 默认 false |
| `API_SERVER_HOST` | `0.0.0.0` | 容器内默认 loopback |
| `API_SERVER_KEY` | `openssl rand -hex 32` | **强制** |
| `HERMES_DASHBOARD` | `1` | 否则 dashboard 不起 |
| `HERMES_DASHBOARD_HOST` | `0.0.0.0` | 别照抄官方示例的 127.0.0.1 |
| `HERMES_DASHBOARD_BASIC_AUTH_*` | 服务账号 | 非 loopback 必须有 auth provider |
| `GATEWAY_MULTIPLEX_PROFILES` | `true` | 启用 `/p/<profile>/` 路由 |

### 8.2.1 Dashboard 鉴权：不是 HTTP Basic，是 cookie 会话

**这点直接影响控制层实现，已实测确认。**

虽然环境变量叫 `HERMES_DASHBOARD_BASIC_AUTH_*`，但 dashboard **不接受** HTTP Basic 头。直接带 `Authorization: Basic` 请求 `/api/profiles` 返回 **401**，且 `logs/dashboard-auth.log` 记录 `reason: "no_cookie"`。

正确流程：

```
1. POST /auth/password-login
   body: {"provider": "basic", "username": "...", "password": "..."}
   → 200 {"ok": true, "next": "/"}
   → Set-Cookie: hermes_session_at / hermes_session_rt / hermes_session_provider

2. 后续所有 /api/* 请求带上这组 cookie
```

可用 provider 通过 `GET /api/auth/providers` 查询：

```json
{"providers": [{"name": "basic", "display_name": "Username & Password", "supports_password": true}]}
```

**对控制层的要求**：

| 项 | 做法 |
|---|---|
| 登录 | 启动/按需调 `/auth/password-login` 换 cookie |
| 会话保持 | `httpx.AsyncClient(cookies=...)` 持有 cookie jar |
| 刷新 | cookie 过期后重新登录，封装 `DashboardClient` 自动重登 |
| 不落地 | dashboard 凭据只存控制层内存/环境变量，绝不下发浏览器 |

**注意**：`password-login` 必须带 `provider` 字段，缺失返回 **422**（不是 401）。这是最容易踩的一步。

### 8.3 不要用 `network_mode: host`

官方示例 compose 用了 `network_mode: host`，但它**无法加入自定义 bridge 网络**，也就无法用容器名互访。控制层要按 `http://hermes-dashboard:9119` 访问 dashboard，必须用 bridge + `ports`。

### 8.4 状态持久化：bind mount（**必须放在 WSL 内部**）

采用**文件夹挂载**而非命名卷，便于直接查看/编辑 profile 目录、SOUL.md、skills。

**但这有一个必须理解的前提：路径必须位于 WSL 的 ext4 文件系统内。**

hermes 的会话库是 SQLite，默认 WAL 模式（`docker.md:302`）：

> WAL relies on shared memory (`state.db-shm`) being coherent between every process that has the file open. Bind mounts that cross a VM boundary do not provide that: **virtiofs** (Docker Desktop on macOS) and **9p / drvfs** (Docker Desktop on Windows) both let concurrent writers **silently corrupt** a WAL database while the main file still passes `PRAGMA integrity_check`.

**关键区分**：

| 挂载来源 | 文件系统 | WAL 安全性 | 结论 |
|---|---|---|---|
| `/mnt/d/...`（Windows 盘） | **9p / drvfs** | ❌ 会静默损坏 | **绝对不能用** |
| `~/agent-gateway/data`（WSL 内） | **ext4** | ✅ 正常 | **推荐** |
| 命名卷 `hermes-data:` | VM 内 ext4 | ✅ 正常 | 可用，但你已选择不用 |

**所以在 WSL 里开发时，数据目录要放在 `~` 下，不能放 `/mnt/c` 或 `/mnt/d`。**

推荐布局（WSL 内）：

```
~/agent-gateway/
├── docker-compose.yml
├── data/                      # ← hermes 数据（ext4，WAL 安全）
│   └── hermes/
└── ...
```

compose 里：

```yaml
services:
  hermes-gateway:
    volumes:
      - ./data/hermes:/opt/data
```

**不要**写成 `/mnt/d/agent/agent-gateway/data/hermes` —— 那是 9p，会损坏数据库。

### 8.5 hermes 的自动降级机制（知道即可，不必依赖）

hermes 自 v2026.9.14 起有检测（`docker.md:306`）：读取容器内 `/proc/self/mountinfo`，发现数据库目录在 virtiofs/9p 上时：

- **新建**数据库 → 自动用 rollback（`DELETE`）journal 模式 + 一次性警告
- **已存在的 WAL 数据库** → **不会热降级**，每次启动记一条 error，`hermes doctor` 会标记

**这意味着**：即使你不小心放到了 `/mnt/d`，新数据库也能跑（自动降级为 DELETE 模式），但会有性能损失和警告噪音。**已存在的 WAL 库**才需要手动修复：

```sh
docker exec hermes python3 -c "import sqlite3; print(sqlite3.connect('/opt/data/state.db').execute('PRAGMA journal_mode=DELETE').fetchone()[0])"
```

并在 `config.yaml` 设 `database.journal_mode: delete`。

**建议**：即便如此，也**不要依赖自动降级**。直接把数据放 WSL 内 ext4，保持 WAL 的性能优势。

### 8.6 WSL 开发的三个注意事项

**1. 用 WSL 内的 Docker，不要用 Docker Desktop 的 Windows 后端**

如果你在 WSL 里跑 `docker compose`，但 Docker 引擎实际是 Docker Desktop 的 Windows 后端，那么 `./data/hermes` 相对路径会被解析成 Windows 路径 → 落到 `/mnt/...` → 又变成 9p。

**检查方法**：

```sh
docker info --format '{{.OperatingSystem}} {{.DockerRootDir}}'
```

如果 `DockerRootDir` 是 `/var/lib/docker`，说明用的是 WSL 原生 Docker（好）。如果是 Windows 路径，说明走的是 Desktop 后端。

**2. `HERMES_UID` / `HERMES_GID` 要匹配 WSL 用户**

WSL 默认用户的 uid 通常是 1000，但 hermes 官方示例用的是 10000（`docker-compose.windows.yml:19`）。bind mount 下 uid 不匹配会导致容器内无法写入：

```sh
id -u   # 查你的 WSL uid
```

compose 里设：

```yaml
environment:
  - HERMES_UID=${UID:-1000}
  - HERMES_GID=${GID:-1000}
```

**3. 文件权限**

bind mount 后，`./data/hermes` 的所有者需要是 `HERMES_UID`。如果 hermes 容器启动报权限错误：

```sh
sudo chown -R 1000:1000 ./data/hermes
```

s6 的 cont-init 会尝试 chown，但如果宿主目录权限过于严格可能失败。

### 8.7 健康检查

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "-H", "Authorization: Bearer ${API_SERVER_KEY}", "http://127.0.0.1:8642/health"]
  start_period: 60s   # 给 s6 跑完 cont-init
```

### 8.8 配置生效语义

| 操作 | 生效方式 |
|---|---|
| 新建 profile | **即时生效**（`served_now`），无需重启 |
| 改已有 profile 的 config/skills | **通常需重载** |
| 改 toolset | 需重载 |

UI 上要区分「已生效」和「生效中」。

---

## 九、前端路由

```
/                      → 跳转：有 token → /admin 或 /chat；无 → /login
/login                 → 登录（管理员 + 用户共用，登录后按 scope 跳转）
/register              → 注册
/chat                  → Agent 列表（用户视角，仅 published）
/chat/{slug}           → 对话页
/chat/{slug}/c/{sid}   → 对话页 + 会话
/admin                 → 管理中心首页（Agent 列表）
/admin/agents/new
/admin/agents/{id}/edit
/admin/a2a
/admin/mcp
/admin/skills
/admin/models
/admin/connectors
```

**路由守卫**：

| 路径 | 要求 |
|---|---|
| `/admin/**` | `scope == "admin"` |
| `/chat/**` | 登录即可（任意 scope） |
| `/login` `/register` | 未登录 |

**统一加 `/chat/` 前缀**的理由：避免 slug 为 `admin` 时与 `/admin` 路由冲突。

---

## 十、实施顺序

```
1. 骨架：compose + hermes 容器跑通
   → 验证：curl /health 通，/api/profiles 可访问

2. 用户体系：users 表 + 注册/登录 + JWT scope
   → 验证：注册→登录→/api/auth/me 返回正确用户

3. Agent 编排：agents 表 + 调 /api/profiles 创建
   → 验证：创建 Agent 后 hermes 里出现 profile，served_now=true

4. 会话归属：conversations 表 + 创建/列表
   → 验证：两个用户各自只看到自己的会话

5. SSE 代理：/api/sessions/{id}/chat/stream → 前端契约
   → 验证：打字机效果正常，工具事件正常，keepalive 不报错

6. 前端：路由改造 + 登录守卫 + 注册页
   → 验证：未登录跳 /login，登录后进 /chat 或 /admin

7. 资源管理：模型/MCP/Skill 的模板 + 下发
   → 验证：改了模型后新会话用新模型
   → Skill 下发含 frontmatter 注入逻辑（§6.5）

8. A2A：出站配置 + 入站 served agents
   → 验证：a2a_discover 能拉到对方卡片
```

---

## 十一、验收标准

### 11.1 用户体系

- [ ] 注册新用户成功，返回 token
- [ ] 重复用户名/邮箱注册返回 409
- [ ] 用户 token 访问 `/admin/**` 返回 403
- [ ] 管理员 token 访问 `/api/auth/me` 返回 403（scope 不匹配）
- [ ] 关掉 `allow_registration` 后注册接口返回 403

### 11.2 Agent 管理

- [ ] 创建 Agent 后，hermes 里存在对应 profile 目录
- [ ] 创建的 Agent `served_now=true`
- [ ] `GET /v1/toolsets` 确认 `public` tier 的 terminal/file/browser 全部 disabled
- [ ] 编辑 Agent 的 SOUL 后，新会话体现新人格

### 11.3 会话隔离（最关键）

- [ ] 用户 A 创建的会话，用户 B 的列表中**不可见**
- [ ] 用户 B 直接猜 ID 访问 A 的会话返回 403/404
- [ ] 删除会话后（软删），该会话从用户列表消失
- [ ] 软删后 hermes 侧 session **仍存在**（可通过 dashboard 验证）
- [ ] 定时任务能硬删超过保留期的会话

### 11.4 Skill 下发

- [ ] 纯文档 skill 在 public tier 正常出现在清单里
- [ ] 带 `scripts/` 的 skill 在 public tier **不出现在清单里**
- [ ] 同一个带脚本 skill 在 admin tier 正常出现，且脚本可执行
- [ ] 下发到 public profile 的 skill 目录里**没有** `scripts/`
- [ ] 下发到 admin profile 的 skill 目录里**有** `scripts/`
- [ ] frontmatter 注入是幂等的（重复下发不会重复追加 `requires_toolsets`）
- [ ] skill 原本已声明 `requires_toolsets` 时，注入后是并集而非覆盖

### 11.5 部署（WSL + bind mount）

**已验证通过（2026-11-16）**：

- [x] 数据目录位于 WSL 内（`/home/niechao/agent-gateway/data/hermes`），不在 `/mnt/*`
- [x] `docker info` 显示 `DockerRootDir=/var/lib/docker`（WSL 原生 Docker）
- [x] `./data/hermes` 所有者为 `niechao:niechao`（uid 1000），与 `HERMES_UID` 一致
- [x] 容器内 `/opt/data/state.db` 的 journal mode 为 **`wal`**（不是 `delete`）
- [x] `hermes` 容器 `RestartCount=0`，180 秒观察窗口内无重启
- [x] `8642`（gateway）与 `9119`（dashboard）同时监听
- [x] 多 profile 路由 `/p/smoke-test/health` 返回 200

### 11.6 骨架连通性（已验证）

- [x] `GET /health` → `{"status":"ok","platform":"hermes-agent","version":"0.23.1"}`
- [x] `POST /auth/password-login`（带 `provider: basic`）→ 200 + 三个 cookie
- [x] `GET /api/profiles`（带 cookie）→ 200，含 default profile
- [x] `POST /api/profiles`（name + soul + description）→ 200，返回 `soul_set: true`
- [x] 新建 profile 已被 gateway 接管（`gateway_running: true`）
- [x] 宿主侧 `data/hermes/profiles/smoke-test/SOUL.md` 内容与提交一致
- [x] 新 profile 的 `config.yaml` 自动生成并继承 default 的模型配置

### 11.7 用户体系（已验证，第 2 步）

单元测试 **14 项全通过**（`control/tests/test_auth.py`），并在真实容器（Postgres + FastAPI）端到端验证：

- [x] `POST /api/auth/register` → 201，返回 token 与用户信息
- [x] 重复用户名 → 409；重复邮箱 → 409
- [x] 用户名格式非法 → 422；密码短于 8 位 → 422
- [x] `POST /api/auth/login` → 200；错误密码 → 401
- [x] 未知用户与错误密码返回**相同**的 401 文案（不泄露用户是否存在）
- [x] `GET /api/auth/me`（带 user token）→ 200
- [x] 无 token → 401；垃圾 token → 401
- [x] **admin scope token 调 `/api/auth/me` → 403**（`{"detail":"需要用户身份"}`）
- [x] **user scope token 调 `get_current_admin` → 403**（`{"detail":"需要管理员身份"}`）
- [x] `ALLOW_REGISTRATION=false` 时注册 → 403
- [x] 数据真正落 Postgres：`users` / `agents` / `conversations` 三张表已建

### 11.8 Agent 编排（已验证，第 3 步）

单元测试 **32 项全通过**（14 auth + 18 agents），并在真实容器 + 真实 hermes 上端到端验证：

- [x] `POST /api/admin/agents` → 201，自动创建 hermes profile
- [x] 返回体含 `profile_name: agent-<slug>`、`disabled_toolsets`（public 档位 9 项）
- [x] `gateway_running: true`：新 profile 被 gateway 立即接管
- [x] 宿主侧 `data/hermes/profiles/agent-e2e-bot/SOUL.md` 内容正确
- [x] dashboard 的 `/api/profiles` 可见该 profile
- [x] 重复 slug → 409
- [x] 非法 slug（大写/空格/超长/`default`/`admin`）→ 422
- [x] **profile 创建失败 → 502 且 DB 回滚**（不留孤儿记录）
- [x] user token 调 admin 接口 → 403
- [x] admin token 调用户接口 → 403
- [x] 未发布 Agent 对用户不可见；publish 后可见；unpublish 后消失
- [x] `toolset_tier` 改为 `admin` → `disabled_toolsets` 变空
- [x] 删除 Agent 同时删除 hermes profile

### 11.8.1 ⚠️ API_SERVER_KEY 会被 `/opt/data/.env` 覆盖

**这是第 3 步踩到的最隐蔽的坑。**

现象：compose 里正确设置了 `API_SERVER_KEY`，容器内 `echo $API_SERVER_KEY` 也能拿到，但所有 `/v1/*` 请求（包括 `/v1/models`、`/v1/toolsets`）全部 **401**。

启动日志里的关键提示（`[stage2] Warning`）：

> `API_SERVER_KEY is set in both the container environment and /opt/data/.env — the .env value wins at runtime (loaded with override=True)`

**根因**：hermes 首次启动时会在 `/opt/data/.env` 生成自己的 `API_SERVER_KEY`，之后每次启动都用 `override=True` 加载该文件，**覆盖**容器环境变量。

实测两个值不同：

| 来源 | 值 |
|---|---|
| 容器环境变量 | `e9460cd5...` |
| `/opt/data/.env` | `0447002a...` ← 实际生效 |

**正确做法（控制层必须遵守）**：

1. 启动时先读 `/opt/data/.env` 里的 `API_SERVER_KEY`（或先调一次 dashboard 触发生成）
2. 用该值作为 `HERMES_API_KEY` 注入控制层
3. **不要**假设 compose 里的 `API_SERVER_KEY` 就是生效值

**验证方法**：

```sh
docker exec ag-hermes grep '^API_SERVER_KEY' /opt/data/.env
```

拿这个值去请求 `/v1/toolsets` 才会 200。

单元测试 **14 项全通过**（`control/tests/test_auth.py`），并在真实容器（Postgres + FastAPI）端到端验证：

- [x] `POST /api/auth/register` → 201，返回 token 与用户信息
- [x] 重复用户名 → 409（提示「用户名已被占用」）
- [x] 重复邮箱 → 409
- [x] 用户名格式非法 → 422
- [x] 密码短于 8 位 → 422
- [x] `POST /api/auth/login` → 200
- [x] 错误密码 → 401
- [x] 未知用户与错误密码返回**相同**的 401 文案（不泄露用户是否存在）
- [x] `GET /api/auth/me`（带 user token）→ 200
- [x] 无 token → 401；垃圾 token → 401
- [x] **admin scope token 调 `/api/auth/me` → 403**（`{"detail":"需要用户身份"}`）
- [x] **user scope token 调 `get_current_admin` → 403**（`{"detail":"需要管理员身份"}`）
- [x] `ALLOW_REGISTRATION=false` 时注册 → 403
- [x] 数据真正落 Postgres：`users` / `agents` / `conversations` 三张表已建

### 11.9 会话归属与 SSE（已验证，第 4 步）

单元测试 **57 项全通过**（14 auth + 22 agents + 21 chat），并在真实 hermes 上端到端验证：

**会话归属**

- [x] `POST /api/chat/conversations` → 201，真调 hermes 创建 session
- [x] `hermes_session_id` 格式 `ag_u{user_id}_{16hex}`
- [x] 标题取首条消息截断（不调 LLM）
- [x] 未发布 Agent 不能建会话 → 404
- [x] **用户 B 的列表里看不到 用户 A 的会话**
- [x] **B 拿 A 的会话 id 对全部 5 个端点操作 → 全部 404**
      （get / messages / delete / restore / stream）
- [x] 软删后列表消失，但 hermes 侧 session **仍在**且未被调用删除
- [x] restore 能恢复软删会话
- [x] hermes 侧确认 session 真实存在（`/api/sessions` 可见 `ag_u2_...`）

**SSE 翻译**

- [x] 真实报文回归：`assistant.delta` → `token`，`assistant.completed` → 收尾
- [x] **keepalive 注释行被跳过**，不中断解析
- [x] `run.failed` → `error` 帧
- [x] 非流式模型（只发 `assistant.completed`）→ 完整内容一次性发出
- [x] 兼容 OpenAI 风格 chunk（防御性）
- [x] `text/event-stream` + `X-Accel-Buffering: no`

**端到端实测结果**（真实 hermes）：

```
stream status: 200
event: token  {"content": "⚠️ I couldn't connect to the AI model service..."}
event: error  {"detail": "运行失败"}
```

翻译层完全正确——`assistant.completed` 的内容被转成 `token`，`run.failed` 被转成 `error`。
**该报错是环境问题（未配置模型 API key），不是代码缺陷。**

### 11.9.1 ⚠️ hermes SSE 的真实格式与文档不同

实测抓包（`ssetest1` 会话）得到的**真实**格式：

```
event: run.started
data: {"session_id":"...","run_id":"run_xxx","seq":1}

event: message.started
data: {"message":{"id":"msg_xxx","role":"assistant"},"seq":2}

: keepalive                          ← 每 10s 无事件时发

event: assistant.delta
data: {"delta":"文本增量","message_id":"msg_xxx","seq":3}

event: assistant.completed
data: {"content":"完整文本","completed":true,"seq":5}

event: run.failed
data: {"error":"...","seq":4}
```

**三个必须注意的点**：

| 项 | 错误写法 | 正确写法 |
|---|---|---|
| 请求体 | `{"messages":[{"role":"user","content":"..."}]}` | **`{"message": "..."}`** |
| 事件名 | `chat.completion.chunk` | **`assistant.delta`** / `assistant.completed` |
| 增量位置 | `choices[0].delta.content` | **顶层 `delta`** 字段 |

请求体写错会返回 **400 `missing_message`**（`_session_chat_user_message` 只认 `message` 或 `input`）。

### 11.9.2 ⚠️ SQLite 不支持 BigInteger 主键自增

`Conversation.id` 最初用 `BigInteger`，在 SQLite（测试用）上插入失败：

```
sqlite3.IntegrityError: NOT NULL constraint failed: conversations.id
```

原因：SQLite 只有 `INTEGER PRIMARY KEY` 才会自增，`BigInteger` 映射成 `BIGINT` 不自增。

**改用 `Integer`**。会话量远达不到 2^31，Postgres 上两者行为一致。

### 11.9.3 对话（前端接入后人工确认）

- [ ] 打字机效果正常（token 流增量渲染）
- [ ] 工具调用显示 `tool_start` / `tool_end`
- [ ] 长工具调用时（>10s）不超时（keepalive 被正确跳过）
- [ ] 刷新页面后历史正确恢复

### 11.9.4 前端（已完成，第 6 步）

构建通过（`pnpm build`），7 个路由全部生成：

```
○ /            ○ /login      ○ /register
○ /admin       ○ /chat
ƒ /chat/[slug] ○ /_not-found
```

**端到端验证（经 nginx :10099）**：

- [x] `/`、`/login`、`/register` 均返回 200
- [x] `POST /api/auth/register` 经 nginx → 201 + JWT
- [x] `POST /api/auth/login` → 200
- [x] 带 token 拉 `/api/chat/agents` → 返回已发布 Agent（含 9 项 disabled_toolsets）
- [x] 创建会话 → 201
- [x] **SSE 经 nginx 逐帧回传，未被缓冲**

### 11.9.5 ⚠️ 前端三个构建坑

**1. MUI 9 的 Typography 不再接受布局类 prop**

```tsx
// ✗ 编译报错 TS2769
<Typography variant="h5" fontWeight={700} textAlign="center">

// ✓ 必须用 sx
<Typography variant="h5" sx={{ fontWeight: 700, textAlign: "center" }}>
```

MUI 9 收紧了 Typography 的 prop 类型，`fontWeight` / `textAlign` 等都不再是直接属性。

**2. 图标命名**

`@mui/icons-material/ChatBubbleOutline`、`/DeleteOutline` 在 9.x 中不存在。
用基础名 `Chat` / `Delete` 最稳妥（所有版本都有）。

**3. `rewrites` 在 build 时求值并写死**

```ts
// next.config.ts
async rewrites() {
  const target = process.env.CONTROL_URL ?? "http://127.0.0.1:8000";
  return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
}
```

第一次打包时 `CONTROL_URL` 是默认值 `127.0.0.1:8000`，部署到容器后**运行时改环境变量无效**，导致 `ECONNREFUSED 127.0.0.1:8000`。

**解决**：作为构建参数传入（Dockerfile 里 `ARG CONTROL_URL` + `ENV CONTROL_URL`），或者干脆让 nginx 直接反代 `/api/*`（当前采用后者，更可控）。

### 11.9.6 开发环境注意：不要在 9p 上跑 pnpm install

`/mnt/d` 是 9p 文件系统，`pnpm install` 会长时间卡在 `node_modules` 创建阶段（实测超时 10 分钟仍未完成）。

**改用 Docker 构建**（镜像内是 ext4），或把 web 目录放到 WSL 原生路径下开发。

### 11.9.7 ⚠️ hermes session 的 title 必须全局唯一（致命）

**这是导致"所有会话创建都失败"的根因。**

```json
// POST /api/sessions {"id": "...", "title": "你好"}
// → 400
{"error": {"message": "Title '你好' is already in use by session abc",
           "code": "invalid_title"}}
```

hermes 对 `title` 做了**全局唯一约束**。而「你好」这种短消息做标题必然撞车——
第二次用同样的话开头，会话就建不出来。

hermes 自己生成标题时会自动加 ` #2` / ` #3` 后缀，但**显式传入的 title 不做处理**。

**解决**：创建 session 时**不要传 title**，标题只在控制层本地生成并展示：

```python
# conversations.py
await gw.create_session(sid)          # 不传 title
conv.title = derive_title(first_message)  # 本地存
```

### 11.9.8 hermes 消息格式与历史恢复

`GET /api/sessions/{id}/messages` 返回：

```json
[
  {"role": "user", "content": "用一句话介绍你自己", "tool_calls": null, "tool_name": null},
  {"role": "assistant", "content": "我是Hermes Agent，...", "tool_calls": null, "tool_name": null},
  {"role": "session_meta", "content": null, "tool_calls": null, "tool_name": null}
]
```

**必须过滤 `session_meta`**（hermes 内部记录），否则前端渲染出空消息。同样要过滤
`system` / `run_meta`。多模态内容（`[{type:"text",text:"..."}]`）需拍平为文本。

控制层在 `routes/chat.py::_normalize_messages` 做这层规范化。

### 11.9.9 Gemini 模型接入（实测踩坑三连）

本地无法直连 Google，且 hermes 的配置有几个反直觉的点。

**坑 1：`OPENAI_API_KEY` 环境变量不生效**

写进 `/opt/data/.env` 也没用——hermes 进程环境里看不到（有白名单）。
必须用 `model.api_key` 内联或引用：

```yaml
model:
  default: "gemini-2.5-flash"
  provider: "custom"
  base_url: "http://127.0.0.1:8899/v1beta/openai"
  api_key: "AIza..."        # ← 必须在这里
```

**坑 2：`provider: gemini` 会发 `thinking_config`，而 flash-lite 不支持**

```
Invalid JSON payload received. Unknown name "thinking_config": Cannot find field.
```

实测对比（同一 key）：

| 模型 | 带 thinkingConfig |
|---|---|
| `gemini-2.5-flash` | ✅ 接受 |
| `gemini-3.5-flash-lite` | ❌ 400 |

所以最终用 `gemini-2.5-flash`（虽然 lite 更便宜，但和 hermes 的 thinking 逻辑不兼容）。

**坑 3：网络需要中转**

本地 WSL 访问 `generativelanguage.googleapis.com` 超时。方案：

```
hermes 容器
  └─ SSH 隧道 127.0.0.1:8899
       └─ srv-01 的 gemini-proxy 容器（nginx 反代 Google）
```

服务器端（srv-01）：

```sh
docker run -d --name gemini-proxy -p 8899:8899 \
  -v /tmp/gemini-proxy/nginx.conf:/etc/nginx/conf.d/default.conf:ro nginx:1.27-alpine
```

容器内启动隧道：`/opt/data/start-tunnel.sh`（见 `scripts/start-tunnel.sh`）。

**注意**：服务器 ufw 只放行 22/80/443，8899 从外部不可达——所以必须用 SSH 隧道，
不能直接连服务器端口。

### 11.9.10 管理员登录（补 `.env` 默认账号）

管理中心需要一个 `scope=admin` 的 token，而用户登录只签发 `scope=user`。
管理员凭据来自环境变量，不需要单独的 admin 表：

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<强密码>
```

`POST /api/auth/admin-login` 校验后签发 admin token。用 `secrets.compare_digest`
防时序攻击；未配置密码返回 503（不是 500）。

### 11.9.11 已验证的真实对话

```
$ curl -N -X POST .../conversations/5/stream -d '{"message":"说一句欢迎词"}'

event: token
data: {"content": "您"}

event: token
data: {"content": "好！"}

event: done
data: {"thread_id": "ag_u5_22de248561a5f4d7"}
```

历史恢复：

```json
{"messages": [
  {"id":"h-0","role":"user","content":"说一句欢迎词"},
  {"id":"h-1","role":"assistant","content":"您好！"}
]}
```

**至此前端 → nginx → 控制层 → hermes → Gemini 全链路跑通。**

### 11.11 管理中心完整功能（已完成）

| 功能 | 端点 | 状态 |
|---|---|---|
| 管理员登录 | `POST /api/auth/admin-login` | ✅ |
| Agent CRUD | `/api/admin/agents*` | ✅ |
| Agent 编辑页 | `/admin/agents/{id}/edit` | ✅ |
| 用户管理 | `GET/PATCH /api/admin/users*` | ✅ |
| Skill 开关 | `/api/admin/agents/{id}/skills*` | ✅ |
| A2A 端点 | `/api/admin/agents/{id}/a2a*` | ✅ |
| 软删清理 | 后台定时任务（24h 一次） | ✅ |

**测试：102 项全通过。**

### 11.11.1 Skill 与 A2A 的实现差异（重要）

这两者 hermes 的接口能力完全不同，实现方式也不同：

| | Skill | A2A |
|---|---|---|
| hermes 支持 | **有 API**（`GET /api/skills?profile=`, `PUT /api/skills/toggle`） | **没有写接口** |
| 实现方式 | 走 dashboard cookie 会话 | **直接改 profile 的 config.yaml** |
| 语义 | profile 级**开关**（不是复制文件） | 写入 `a2a_agents` 段 |
| 生效 | 立即可用 | 需重载 profile |

**A2A 为什么不用 `hermes config set`**：那需要 docker CLI + `docker.sock`，
等于把宿主机 root 权限交给控制层；而 apt 安装 docker CLI 在国内环境下会超时。
改为直接读写文件后，控制层只需挂载 hermes 数据目录。

**直接写文件的代价与对策**：

```python
# 原子写：临时文件 + fsync + rename
fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cfg-", suffix=".tmp")
# ... 写入并 fsync ...
os.replace(tmp, path)   # 原子替换
```

- 用 `yaml.safe_load` → 修改 → `yaml.safe_dump`，**保留 model 等其他段**
- 写入失败**不回滚 DB**，接口返回 `apply_error`，用户可修好环境后重试
- 整体替换 `a2a_agents` 段，避免残留已删除端点

### 11.11.2 软删清理任务

`control/app/scheduler.py`：

- 应用启动后 **60 秒**首次执行（避开建表/迁移）
- 之后每 **24 小时**一次
- 优雅停止：lifespan 关闭时 `await task.stop()`
- 幂等启动：重复 `start()` 不新建任务

清理逻辑在 `conversations.hard_delete_expired()`：
先调 hermes `DELETE /api/sessions/{id}`，再删控制层记录。

### 11.11.3 隧道自动化

`scripts/99-tunnel` 挂到 `/etc/cont-init.d/`，容器启动时自动建 SSH 隧道。

两个踩到的坑：

1. **私钥权限**：root 创建的 `600` 文件 hermes 读不到 → 必须 `chown hermes:hermes`
2. **`s6-setuidgid` 不在 PATH**：cont-init 阶段要用绝对路径探测
   （`/command/` 或 `/package/admin/s6/command/`）

设计取舍：隧道失败**不阻塞**容器启动（`exit 0`），因为 hermes 本身仍可用，
只是模型调用会失败——比容器起不来更容易排查。

### 11.11.4 A2A 入站（已完成）

启用方式：在 hermes 的 `.env` 里配置后重启。

```env
A2A_HOST=0.0.0.0
A2A_PORT=9900
A2A_BEARER_TOKEN=<强随机值>
A2A_TRUSTED_PEERS=ip:127.0.0.1
```

**三项缺一不可**（实测，对应 §7.3）：

| 缺失项 | 症状 |
|---|---|
| 无 token | 只绑 `127.0.0.1`，外部不可达 |
| 无 `A2A_HOST=0.0.0.0` | 出不了容器 |
| 无 `A2A_TRUSTED_PEERS` | dispatch 返回 `peer 'ip:x' not trusted`（403） |

第三条最隐蔽：**服务能起、Agent Card 能拉到，但请求被拒**。

验证结果：

```
POST /a2a  message/send
→ 200 {"result": {"status": {"state": "TASK_STATE_COMPLETED",
                             "message": {"parts": [{"text": "收到"}]}}}}
```

Agent Card 暴露 **32 个 skills**，`capabilities.streaming = true`。

**探测地址的坑**：控制层与 hermes 在不同容器，探测必须用 compose 主机名
`http://ag-hermes:9900`，不能用 `127.0.0.1`（否则 `reachable` 永远 false）。

### 11.11.5 前端单元测试

`web/src/lib/sse.test.ts` + `sseStream.test.ts`，**17 项**：

- keepalive 跳过（单独 / 混在块内）
- 空块、只有 event 无 data、多行 data 拼接
- CRLF 兼容、data 冒号后空格剥离
- **按任意字节边界切分仍能解析**（模拟网络分片）
- 非法 JSON 跳过不崩溃

本地 `pnpm` 装不上（9p 文件系统），运行方式：

```sh
docker build --target base -t ag-web-test ./web
docker run --rm ag-web-test pnpm test
```

### 11.10 安全
- [ ] 无 `visitor` 相关代码残留
- [ ] 无 speech/tts/asr 相关代码残留
- [ ] `public` tier 的 Agent 无法执行 terminal 命令
- [ ] dashboard 端口不对外暴露

---

## 十二、已确认的决策

| # | 问题 | 决策 |
|---|---|---|
| 1 | 是否开放自助注册？ | **开放，但带配置开关** `settings.allow_registration`（关掉后注册接口返回 403） |
| 2 | 用户能否看到多个 Agent？ | **看到所有 published 的 Agent**，不做授权粒度 |
| 3 | 会话标题怎么生成？ | **首条消息截断**（省 token，不调 LLM） |
| 4 | 用户删除会话后是否真删 hermes 侧？ | **软删**（B）——见下方说明 |
| 5 | 是否保留连接器（飞书/Slack）？ | **保留** |
| 6 | Skill 的 `scripts/` 对 public 是否部署？ | **不部署 `scripts/`，并自动注入 `requires_toolsets: [terminal]`**（见 §6.5） |

### 12.1 关于决策 4（软删）的实现

你选择了软删，这与默认设计不同，需要明确语义。

**软删意味着**：

```
DELETE /api/chat/conversations/{id}
   ↓
控制层标记 conversations.deleted_at = now()
   ↓
【不调用】hermes DELETE /api/sessions/{id}
   ↓
用户列表不再显示（WHERE deleted_at IS NULL）
```

**需要补充的字段**：

```python
class Conversation(Base):
    ...
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
```

**软删带来的三个后果，必须提前处理**：

| 后果 | 说明 | 处理 |
|---|---|---|
| hermes 侧会话持续累积 | 不删则 state.db 一直增长 | 需要一个定期清理任务（见下） |
| 用户「恢复会话」成为可能 | 软删的天然好处 | 可选的回收站功能，暂不实现 |
| 同名/同 ID 重建 | 用户删了再新建，不应复用旧 ID | 新建永远生成新 `hermes_session_id` |

**必须配套的清理策略**（否则磁盘会一直涨）：

建议加一个定时任务，硬删超过 N 天的软删记录：

```python
# 建议 30 天
DELETE FROM conversations
WHERE deleted_at IS NOT NULL
  AND deleted_at < now() - interval '30 days'
```

删除前先调 `hermes DELETE /api/sessions/{hermes_session_id}`，成功后再删控制层记录。

**为什么不能只软删不管**：hermes 的 `state.db` 是单个 SQLite 文件，会话消息全在里面。不清理的话，几个月后这个文件会很大，且 SQLite 的 VACUUM 需要停机。

**建议的折中**：软删保留 30 天（给用户「误删恢复」的窗口），之后由定时任务硬删。这个 30 天是可配的（`settings.soft_delete_retention_days`）。

---

## 十三、风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| **hermes session 无用户归属** | 越权访问他人会话 | 控制层强制归属校验，绝不透传 `/api/sessions` |
| **`api_server` 预设保留 terminal** | 用户获得容器 shell | 必须显式配 `disabled_toolsets`，用 `/v1/toolsets` 验证 |
| **keepalive 行导致 SSE 解析失败** | 长对话中断 | 前端解析器跳过 `:` 开头的行 |
| **修改 profile 需重载** | 配置不生效 | UI 显示"生效中"，提供手动重载按钮 |
| **bind mount 落在 `/mnt/*` 导致 WAL 损坏** | 数据库静默损坏 | 数据目录放 WSL 内 ext4（`~/`），不放 `/mnt/c` `/mnt/d` |
| **漏设 `command: gateway run` 导致容器无限重启** | 服务不可用，端口漂移 | compose 里显式写 `command: ["gateway", "run"]`（§8.1.1） |
| **拆成两个容器共享 `/opt/data`** | dashboard 反复崩溃、抢锁 | hermes 必须单容器（§8.1） |
| **dashboard 用 HTTP Basic 认证** | 所有 /api 请求 401 | 走 `/auth/password-login` 换 cookie（§8.2.1） |
| **`password-login` 缺 `provider` 字段** | 422 而非 401，难排查 | body 必须含 `{"provider":"basic",...}` |
| **`API_SERVER_KEY` 被 `/opt/data/.env` 覆盖** | 所有 `/v1/*` 莫名 401 | 从 `/opt/data/.env` 读实际生效值（§11.8.1） |
| **`docker compose up` 不重建镜像** | 新代码不生效，路由 404 | 改代码后必须 `docker compose build` 再 `up` |
| **hermes SSE 格式与 OpenAI 不同** | 400 missing_message / 无输出 | 请求体用 `{"message":...}`，事件名 `assistant.delta`（§11.9.1） |
| **SQLite 上 BigInteger 主键不自增** | 测试插入失败 | 主键用 `Integer`（§11.9.2） |
| **忘记挂载 .env 给控制层** | 会话创建 401 | compose 里只读挂 hermes 数据目录（§11.8.1） |
| **WSL 用 Docker Desktop 后端** | 相对路径被解析成 Windows 路径 | 用 WSL 原生 Docker，`docker info` 验证 `DockerRootDir` |
| **HERMES_UID 与 WSL 用户不匹配** | 容器无法写入挂载目录 | `id -u` 查实际 uid，compose 里设对 |
| **软删会话无限累积** | state.db 持续增长 | 30 天保留期 + 定时硬删任务 |
| **带脚本 skill 在 public 下断链** | agent 行为不一致、白占 token | 自动注入 `requires_toolsets: [terminal]` 使其隐藏（§6.5） |
| **误给纯文档 skill 注入 requires_toolsets** | 纯文档 skill 在 public 下消失 | 只对含 `scripts/` 的 skill 注入 |
| **A2A 三项环境变量漏配** | 入站静默失败 | 部署检查清单 |
| **Dockerfile 依赖 ghcr.io 导致构建卡死** | 无法构建镜像 | 不用 `ghcr.io/astral-sh/uv`，直接 pip + 国内镜像源（见 §8.9） |

### 13.1 构建注意：不要依赖 ghcr.io

实测：`COPY --from=ghcr.io/astral-sh/uv:latest` 在国内网络下会卡住（拉取 fs layer 到 13.63/19.57MB 后停滞 887 秒），**且会连带阻塞整个 build**。

**控制层 Dockerfile 已改为直接 pip**，并支持构建参数切换镜像源：

```dockerfile
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
```

```sh
# 国内构建
docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t ag-control:dev ./control
```

实测：用清华源后构建 **19 秒**完成；默认 PyPI 源会卡几分钟到十几分钟。

---

## 十四、与旧仓库的关系

**不迁移任何代码逻辑，仅作功能参照。**

可参考的：

| 文件 | 参考价值 |
|---|---|
| `web/src/lib/api.ts` | SSE 解析器（需加 keepalive 跳过） |
| `web/src/components/admin/AgentForm.tsx` | 表单结构 |
| `src/a2a_gateway/connectors/` | 连接器实现（如保留） |
| `src/a2a_gateway/auth_scheme.py` | 密码哈希方案 |

**不要参考的**：

- `graph.py` / `agent_factory.py` / `llm.py`（LangGraph 运行时，全部废弃）
- `repository.py` 的快照机制（profile 目录即快照）
- `pending_store.py`（改用 context_id）
- `routes/speech.py`（功能已删）
- `identity.py` 的 visitor 分支
