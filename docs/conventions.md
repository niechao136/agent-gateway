# 约定与命令

## 目录约定

- `control/app/routes/<能力>.py`：一个能力一个路由模块；资源级 CRUD 放 `/api/<res>`，Agent 绑定放 `agent_router`（prefix `/api/agents`）。
- `control/app/hermes/<能力>_sync.py`：**写 profile 的翻译层**。原子写 + 整体替换对应段，失败降级为警告不阻断 DB。
- `control/app/models.py`：所有 ORM 表集中定义；新表由 `create_all` 建，改已有表必须显式 DDL。
- `control/tests/test_<能力>.py`：与路由/模块一一对应；conftest 提供 `client`、`atok`、`session_factory`、`FakeGateway`、`FakeDashboard`。
- `web/src/app/admin/<能力>/page.tsx`：`GuardedShell + AdminShell` 包裹的管理页。
- `web/src/lib/api.ts`：所有类型与接口集中在此；后端改 schema 必须同步改这里。

## 编码约定

- FastAPI 依赖注入优先用默认参数风格 `x: T = Depends(get_session)`；`Annotated[..., Depends(...)]` 在本项目曾触发 Pydantic schema 递归（尤其与 `Request` 组合），避免。
- 合并式配置写入：修改 `mcp.servers` / `platform_toolsets` / `.env` 前先读现有内容，按 name/key 合并，避免覆盖其他资源。
- 绑定类写操作：先 `DELETE` 旧绑定 → `await session.flush()` → 再 `INSERT` 新绑定（否则同主键唯一约束冲突）。
- 密钥：DB 存明文；接口只给 `has_api_key: bool` + 掩码；profile `.env` 权限 600；日志不打印。
- 前端 MUI 9：`Stack`/`Typography` 不接受 `alignItems`/`noWrap`/`fontWeight` 作为 prop，一律走 `sx`；`ListItemText`/`Drawer` 用 `slotProps`。
- 前端复制：用 `lib/clipboard.ts::copyText`（HTTP 非安全上下文回退 `execCommand`），不要直接用 `navigator.clipboard.writeText`。
- 主题：`ThemeRegistry` 单一主题由 `theme.tsx` 的 `resolved` 状态驱动，不用 MUI colorSchemes（曾导致亮暗反色）。

## 命令

```bash
# 后端测试（本地 Docker；本地必须清华源）
docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t agent-gateway-control:latest ./control
docker run --rm agent-gateway-control:latest python -m pytest tests/ -q
# 服务器测试（挂载源码，快）：docker run --rm -v /github/agent-gateway/control:/app -w /app \
#   agent-gateway-control:latest python -m pytest tests/ -q -p no:cacheprovider

# 前端（Windows 本地；不要在 WSL /mnt/d 跑 pnpm install）
cd web && pnpm test && pnpm exec tsc --noEmit && pnpm build
# Docker 兜底：docker build --target base -t ag-web-test ./web && docker run --rm ag-web-test pnpm test

# 部署（srv-01）
cd /github/agent-gateway
sudo -u devops git pull origin master
sudo -u devops docker compose --env-file .env --profile full build   # 改代码后必 build
sudo -u devops docker compose --env-file .env --profile full up -d --no-build
```

## 环境与坑（实测）

| 场景 | 坑 / 正确做法 |
|---|---|
| 本地 WSL `/mnt/d` | 9p 文件系统，`pnpm install` 卡死；前端测试走 Windows 本地或 Docker |
| 后端镜像 | 本地用清华源；服务器用默认源更快 |
| 改代码后 | 必须 `docker compose build`，`up` 不会重建镜像 |
| Hermes API key | `/opt/data/.env` 以 `override=True` 覆盖容器环境变量；控制层运行时读文件（`resolve_api_key`） |
| profile 路由 | 必须 `/p/{profile}/...` 且用 profile 专属 key；无前缀走 default profile（无模型 → 报 not connected） |
| toolset 启停 | 真实字段是 `platform_toolsets.api_server`；`hermes -p <profile> tools enable a2a` 才是正确命令（HERMES_PROFILE 环境变量无效） |
| 飞书 SDK | event_handler 必须 `EventDispatcherHandler.builder().register_p2_im_message_receive_v1(...).build()`；WS `start()` 要在独立线程且该线程先 `set_event_loop(new_loop())` 再 import SDK；发消息必须 builder 内 `.request_body(body)` |
| Git push | Windows Git + `$env:HTTPS_PROXY='http://127.0.0.1:10808'`；WSL 直连 GitHub 常超时 |
| 服务器测试 | 全量 pytest 约 80s 会被 srv_exec 60s watchdog 杀；用后台 job 或直接看 `/tmp/pytest_full.log` |
| 文件系统 | 偶发 EISDIR/fsync 错误；脚本文件用 Python `Path.write_text` 或写入后校验行数，关键文件改前先备份/确认 git 可恢复 |
