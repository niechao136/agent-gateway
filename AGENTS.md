# AGENTS.md — agent-gateway 入口

> 本文件是 AI Agent / 新开发者的**唯一入口**。从这里出发，按链接深入。
> 不要把事实堆在这里；事实在 `docs/specs/`，现状在 `docs/STATUS.md`。

## 一句话定位

基于 **Hermes Agent** 的多 Agent 管理平台：**一个平台 Agent = 一个 Hermes profile（独立目录）**。
控制层（FastAPI）负责多租户/权限/编排/配置编译，Hermes 负责 LLM 推理、工具执行、会话。

## 目录地图（必读）

| 我想知道… | 去哪 |
|---|---|
| 项目功能一览（面向人） | [README.md](README.md) |
| 模块边界、C4 context/container | [docs/architecture.md](docs/architecture.md) |
| 编码约定、目录约定、常用命令 | [docs/conventions.md](docs/conventions.md) |
| 现在是什么样（事实来源，按能力） | [docs/specs/](docs/specs/) |
| 当前状态（只写现状，不写流水） | [docs/STATUS.md](docs/STATUS.md) |
| 为什么这么设计（决策记录） | [docs/decisions/](docs/decisions/) |
| 正在改什么 / 最近一次变更 | [docs/changes/](docs/changes/) |

**已完成变更（归档）**：RAGFlow 多站点 — [proposal](docs/changes/2026-11-24-ragflow-multi-site/proposal.md) · [design](docs/changes/2026-11-24-ragflow-multi-site/design.md) · [tasks](docs/changes/2026-11-24-ragflow-multi-site/tasks.md)

## 命令（在仓库根）

```bash
# 后端测试（本地 Docker，本地必须清华源）
docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t agent-gateway-control:latest ./control
docker run --rm agent-gateway-control:latest python -m pytest tests/ -q

# 前端（本地 Windows 直接跑；WSL 的 /mnt/d 是 9p，pnpm install 会卡死）
cd web && pnpm test && pnpm exec tsc --noEmit && pnpm build

# 生产部署（srv-01 新加坡，/github/agent-gateway）
git push origin master
ssh ubuntu@43.156.187.79 'cd /github/agent-gateway && git pull'
docker compose --env-file .env --profile full build   # 改代码后必须 build，up 不会重建
docker compose --env-file .env --profile full up -d --no-build
```

完整命令与坑见 [docs/conventions.md](docs/conventions.md)。

## 红线（不可违反）

1. **一个 Agent = 一个 Hermes profile**。profile 名格式 `agent-u{owner_id}-{slug}`。
2. **Hermes 内置工具只能按 toolset 整组开关**，无法单工具禁用（`hermes tools disable web_search` 报 Unknown toolset）。UI 为开关网格 + 内含工具只读展示。
3. **工具集真实启停由 profile 的 `platform_toolsets.api_server` 控制**；`disabled_toolsets` 只是我们前端的开关镜像。绑定资源强制开启的工具集，写入时两者都要处理。
4. **对外 API 用 Messages 语义**（`/v1/agents/{slug}/messages`），不做 OpenAI 兼容格式——Agent 有 profile/skills/会话状态，不是无状态 completion。
5. **连接器全部长连接**，不用 webhook、不要公网域名/加密配置。
6. **密钥不回明文、不进日志**：api_key 只存 DB + profile `.env`（权限 600），接口最多返回 `has_api_key` + 掩码。
7. **控制层与 Hermes 的桥接层是 bug 高发区**：profile 路由 `/p/{profile}/...` + profile 专属 `API_SERVER_KEY = sha256(全局key+profile名)`；改这块必须跑对话端到端。
8. **生产数据策略**：用户已授权"丢弃重建"，不写迁移脚本；但 `create_all` 不会 ALTER 已存在的表，改结构需显式 DDL。
9. **push 用 Windows Git + `http://127.0.0.1:10808` 代理**（WSL 直连 GitHub SSL 常超时）。

## 工作约定

- 先读本文件 → 按链接读 specs/STATUS → 再动手。
- 改代码前说明思路，改后说明验证方式；用户确认后进入下一阶段。
- 每批/每步完成即提交 + 跑测试；不积累到最后。
- 遇到规格没写清的先问，不自行假设。
- 更多协作约定见 [docs/conventions.md](docs/conventions.md)。
