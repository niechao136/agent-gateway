"""数据模型：users / agents / conversations。

设计要点（见 SPEC.md）：
- users 与 admin_users 是两套独立体系（admin_users 由 hermes dashboard 侧承担）
- agents 只存元数据，真正配置在 hermes profile 目录里
- conversations 只存归属映射，消息正文在 hermes 的 state.db
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AgentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # v2：单一用户体系，role 区分普通用户与管理员（SPEC-v2 决策 1）
    role: Mapped[str] = mapped_column(
        String(16), default=UserRole.USER, server_default=UserRole.USER
    )
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # hermes profile 名（与 slug 解耦，允许改名而不动 profile 目录）
    # v2 命名：agent-u{owner_id}-{slug}（SPEC-v2 决策 3）
    profile_name: Mapped[str] = mapped_column(String(64), unique=True)
    # v2：归属（SPEC-v2 决策 2）。管理员代建时也记 admin 自己。
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=AgentStatus.DRAFT, server_default=AgentStatus.DRAFT
    )
    # v2：toolset_tier 删除，直接存禁用列表（默认 = 只读助手）
    disabled_toolsets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 该 Agent 是否启用 Hermes curator（技能策展器）。NULL 表示跟随全局默认（关闭）。
    curator_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent")
    a2a_endpoints: Mapped[list["A2AEndpoint"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class ModelTemplate(Base):
    """模型模板：可复用的模型配置，下发给 profile 的 config.yaml: model 段。

    存在控制层的理由：用户不想每次创建 Agent 都手填 provider/base_url/api_key。
    """

    __tablename__ = "model_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 批次 2：共享后所有用户可见（只读），仅 owner/admin 可改删
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    provider: Mapped[str] = mapped_column(String(64), default="custom")
    model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Hermes 要求模型上下文 >= 64000（_enforce_minimum_context），小窗口本地模型
    # 需在此声明覆盖，apply-model 时写入 profile config.yaml 的 model.context_length。
    context_length: Mapped[int] = mapped_column(Integer, default=64000, server_default="64000")
    # API key 明文存控制层 DB（个人项目可接受；生产应改用引用）
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── 批次 2：MCP 独立表 ────────────────────────────────────
class MCPServer(Base):
    """MCP 服务器资源：控制层唯一真相，绑定后同步写入 profile config.yaml。

    五方式鉴权（SPEC-v2）：none/bearer/header/query/basic，
    HTTP 面生成 headers/query，stdio 面生成子进程 env（见 hermes/auth_scheme.py）。
    """

    __tablename__ = "mcp_servers"
    __table_args__ = (
        Index("ix_mcp_servers_owner_name", "owner_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # stdio | sse | http | streamable_http
    transport: Mapped[str] = mapped_column(String(24), default="stdio")
    # stdio
    command: Mapped[str | None] = mapped_column(String(255), nullable=True)
    args: Mapped[list | None] = mapped_column(JSON, nullable=True)
    env: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # http 系
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 五方式鉴权
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 共享后所有用户可绑定（只读），仅 owner/admin 可改删
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentMCPServer(Base):
    """Agent ↔ MCP 服务器绑定。"""

    __tablename__ = "agent_mcp_servers"
    __table_args__ = (
        Index("ix_agent_mcp_pair", "agent_id", "mcp_server_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    mcp_server_id: Mapped[int] = mapped_column(
        ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True
    )


class A2AOutboundEndpoint(Base):
    """A2A 出站端点资源（独立表，绑定到多个 Agent）。"""

    __tablename__ = "a2a_outbound_endpoints"
    __table_args__ = (
        Index("ix_a2a_out_owner_name", "owner_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # external=外部 A2A 服务；internal=本平台其它 Agent（经 /a2a/{slug} 调用）
    target_type: Mapped[str] = mapped_column(String(16), default="external", server_default="external")
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(String(512))
    capabilities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    timeout: Mapped[int] = mapped_column(Integer, default=120)

    # 五方式鉴权
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentA2AEndpoint(Base):
    """Agent ↔ A2A 出站端点绑定。"""

    __tablename__ = "agent_a2a_endpoints"
    __table_args__ = (
        Index("ix_agent_a2a_pair", "agent_id", "endpoint_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[int] = mapped_column(
        ForeignKey("a2a_outbound_endpoints.id", ondelete="CASCADE"), index=True
    )


# ── 批次 2：Skill 双来源 ──────────────────────────────────
class CustomSkill(Base):
    """自定义 Skill：控制层存正文，绑定后同步写入 profile 的 skills/ 目录。"""

    __tablename__ = "custom_skills"
    __table_args__ = (
        Index("ix_custom_skills_owner_name", "owner_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SKILL.md 正文
    content: Mapped[str] = mapped_column(Text)
    # 附加文件 {filename: content}
    files: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentCustomSkill(Base):
    """Agent ↔ 自定义 Skill 绑定。"""

    __tablename__ = "agent_custom_skills"
    __table_args__ = (
        Index("ix_agent_skill_pair", "agent_id", "skill_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("custom_skills.id", ondelete="CASCADE"), index=True
    )


class BuiltinSkillState(Base):
    """内置 Skill 的控制层启停状态（级联禁用的决策记录）。"""

    __tablename__ = "builtin_skill_states"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentBuiltinSkill(Base):
    """Agent ↔ 内置 Skill 选择（按 Agent 隔离，SPEC 修复）。

    hermes 的 skill 开关本来就是按 profile 隔离的；这里在控制层记录
    每个 Agent 选了哪些内置技能，默认全不选。勾选时对该 profile 调
    hermes toggle，取消时同理。与自定义 Skill 用完全独立的表/ID 空间。
    """

    __tablename__ = "agent_builtin_skills"
    __table_args__ = (
        Index("ix_agent_builtin_skill_pair", "agent_id", "skill_name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    skill_name: Mapped[str] = mapped_column(String(64), index=True)


# ── 批次 3：对外 API ──────────────────────────────────────
class AgentAPIKey(Base):
    """对外 API Key：按 Agent 隔离（SPEC-v2 决策）。

    - 手动生成（用户拍板）：创建 Agent 不自动发 Key
    - key_hash = SHA-256(明文)；DB 泄露不暴露 Key
    - key_prefix = "agk_" + 前 8 位，列表展示用
    - 明文仅创建响应返回一次（用户拍板）
    """

    __tablename__ = "agent_api_keys"
    __table_args__ = (
        Index("ix_apikey_agent_name", "agent_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── 批次 3：连接器 ────────────────────────────────────────
class Connector(Base):
    """平台连接器：一个连接器绑定一个 Agent，长连接收发消息。

    credentials 存平台 SDK 需要的 token/secret（接口返回脱敏）。
    """

    __tablename__ = "connectors"
    __table_args__ = (
        Index("ix_connector_owner_name", "owner_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # telegram | feishu | slack
    platform: Mapped[str] = mapped_column(String(24))
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    credentials: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # 最近一次收到消息的会话 ID（chat_id）。定时任务的 connector 回报用它作为目标，
    # 否则无法知道往哪个会话发消息。
    default_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class A2AEndpoint(Base):
    """A2A 出站端点：定义在控制层，下发到 profile 的 config.yaml。

    一个 Agent 可以有多个端点（对应 hermes 的 a2a_agents.<name>）。
    """

    __tablename__ = "a2a_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )

    # 会成为 config.yaml 里的 key，必须符合 YAML 安全标识符
    name: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))

    # a2a_orchestrate 的路由依据
    capabilities: Mapped[list | None] = mapped_column(JSON, nullable=True)

    timeout: Mapped[int] = mapped_column(Integer, default=120)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    agent: Mapped["Agent"] = relationship(back_populates="a2a_endpoints")


class Conversation(Base):
    __tablename__ = "conversations"

    # 用 Integer 而非 BigInteger：SQLite 只有 INTEGER PRIMARY KEY 才会自增，
    # BigInteger 在 SQLite 上不会生成 id（Postgres 两者都可）。
    # 单表会话量远达不到 2^31，无需 BigInteger。
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)

    # hermes 侧的 session id（唯一事实来源在此）
    hermes_session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 软删（SPEC §12.1）：非空表示用户已删除，但 hermes 侧仍保留
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    agent: Mapped["Agent"] = relationship(back_populates="conversations")


# 用户列表按 user + 未删除过滤，是最高频查询
Index("ix_conversations_user_active", Conversation.user_id, Conversation.deleted_at)


# ── 知识库（RAGFlow）：站点 + 库两层 ────────────────────────
class RagflowSite(Base):
    """一个 RAGFlow 站点（连接信息）。同站点可挂多个知识库。"""

    __tablename__ = "ragflow_sites"
    __table_args__ = (Index("ix_ragflow_site_owner_name", "owner_id", "name", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))
    api_key: Mapped[str] = mapped_column(String(512))
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeBase(Base):
    """RAGFlow 站点下的一个知识库（dataset）。

    连接信息在 RagflowSite；owner_id 仅冗余快照，权限以 site.owner_id 为准。
    绑定到 Agent 后，检索工具写入该 Agent 的 profile。
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = (Index("ix_kb_site_dataset", "site_id", "dataset_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("ragflow_sites.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="ragflow")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TaskRun(Base):
    """定时任务执行记录。"""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(16), default="ok")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AgentKnowledgeBase(Base):
    """Agent ↔ 知识库绑定（多对多）。"""

    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (
        Index("ix_agent_kb_pair", "agent_id", "kb_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )


class ScheduledTask(Base):
    """定时自动化任务：cron/interval 触发 Agent 消息或 A2A 调用，结果按多选方式处理。"""

    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    schedule_kind: Mapped[str] = mapped_column(String(16), default="interval")
    every_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_type: Mapped[str] = mapped_column(String(16), default="agent_message")
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    a2a_endpoint_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="")
    delivery: Mapped[str] = mapped_column(String(255), default="session,log")
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    connector_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
