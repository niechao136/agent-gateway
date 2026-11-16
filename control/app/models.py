"""数据模型：users / agents / conversations。

设计要点（见 SPEC.md）：
- users 与 admin_users 是两套独立体系（admin_users 由 hermes dashboard 侧承担）
- agents 只存元数据，真正配置在 hermes profile 目录里
- conversations 只存归属映射，消息正文在 hermes 的 state.db
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AgentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ToolsetTier(StrEnum):
    PUBLIC = "public"      # 普通注册用户：无 terminal/file/browser
    MEMBER = "member"      # 信任用户：额外放开 memory/session_search
    ADMIN = "admin"        # 管理员测试：全开


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    profile_name: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(
        String(16), default=AgentStatus.DRAFT, server_default=AgentStatus.DRAFT
    )
    toolset_tier: Mapped[str] = mapped_column(
        String(16), default=ToolsetTier.PUBLIC, server_default=ToolsetTier.PUBLIC
    )
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
    provider: Mapped[str] = mapped_column(String(64), default="custom")
    model: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # API key 明文存控制层 DB（个人项目可接受；生产应改用引用）
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
