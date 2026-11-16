"""配置：全部来自环境变量（与 docker-compose 的 control.environment 对应）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── 数据库 ──
    database_url: str = "postgresql+asyncpg://agent_gateway:changeme@localhost:5432/agent_gateway"

    # ── 鉴定 ──
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 天

    # ── 默认管理员（来自 .env）──
    # 因为不需要单独的管理员表，管理中心账号由环境变量提供。
    # 生产环境务必改掉默认密码。
    admin_username: str = "admin"
    admin_password: str = "admin12345"

    # ── 注册开关（SPEC §12 决策 1）──
    allow_registration: bool = True

    # ── hermes（控制层访问用）──
    hermes_dashboard_url: str = "http://ag-hermes:9119"
    hermes_dashboard_user: str = "admin"
    hermes_dashboard_password: str = ""
    hermes_gateway_url: str = "http://ag-hermes:8642"

    # hermes 的 API_SERVER_KEY。
    # ⚠️ hermes 会用 override=True 加载 /opt/data/.env，其中的同名变量会**覆盖**
    #    容器环境变量。所以 compose 里传进来的值往往不是实际生效值。
    #    若设置了 hermes_dotenv_path，控制层会在运行时优先读该文件
    #    （见 hermes/gateway.py::resolve_api_key）。
    hermes_api_key: str = ""
    hermes_dotenv_path: str = "/opt/hermes-data/.env"
    # hermes 数据目录（控制层挂载为读写，用于 A2A 配置写入）
    hermes_data_root: str = "/opt/hermes-data"

    # ── 会话软删保留期（SPEC §12.1 决策 4）──
    soft_delete_retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
