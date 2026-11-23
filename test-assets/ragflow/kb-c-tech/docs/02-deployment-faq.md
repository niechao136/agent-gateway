# 部署与运维 FAQ

文档编号：TECH-OPS-V1。

## 服务与端口

| 服务 | 端口 | 说明 |
|---|---|---|
| nginx | 10100 | 对外统一入口 |
| control | 8000（容器内） | FastAPI 控制层 |
| hermes dashboard | 9119（容器内） | profile 管理 API + Web UI |
| hermes gateway | 8642（容器内） | 对话 API |
| postgres | 5432（容器内） | 数据库 |

## 常见问题

- **保存配置报 500 PermissionError**：control 容器需以数据目录属主的 uid 运行（当前 `1002:1003`），与 hermes 用户一致。
- **对话报 "not connected to any AI provider"**：请求未走 profile 路由，需带 `/p/{profile}/` 前缀 + profile 专属 API_SERVER_KEY。
- **A2A 调用不触发**：除绑定端点外，必须开启 a2a 工具集（写 `platform_toolsets.api_server`），且内部端点需绝对 URL + API Key 鉴权。
- **带脚本的 Skill 不生效**：必须开启 terminal 工具集，否则脚本被自动剥离。
- **改代码后不生效**：必须 `docker compose build`，`up` 不会重建镜像。

## 数据策略

- 生产部署采用"数据丢弃重建"，不写迁移脚本；新表靠 `create_all` 自动创建。
- 本地 WSL 的 `/mnt/d` 是 9p 文件系统，pnpm install 会卡死，前端测试走 Docker 或 Windows 本地。
