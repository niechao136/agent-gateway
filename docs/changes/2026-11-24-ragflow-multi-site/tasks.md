# Tasks — RAGFlow 多站点（已全部完成，2026-11-24）

完整计划见归档：`docs/superpowers/plans/2026-11-24-ragflow-multi-site.md`；执行台账：`.superpowers/sdd/2026-11-24-ragflow-multi-site/progress.md`。

| # | 任务 | 验证 |
|---|---|---|
| 1 | 数据模型 + rag_env base64 helper | test_rag_env 3 passed |
| 2 | 站点路由（独立前缀/CRUD/脱敏/级联） | test_ragflow_sites 6 passed 1 skipped |
| 3 | 库路由按 site_id 改造 | 8 passed 1 skipped |
| 4 | rag_sync 多站点下发 + 600 权限 | 11 passed 1 skipped |
| 5 | MCP 多站点路由 + site_errors | 4 passed |
| 6 | 定时任务 ingest join site | 编译通过 |
| 7 | 前端 api.ts + 知识库页重写 | tsc（编辑页两处由 Task 8 修复） |
| 8 | Agent 编辑页去重 + 类型修复 | tsc 零错误 |
| 9 | 部署：DDL 改结构 + 重建镜像 + 端到端 | E2E 全通过；全量 220 passed 1 skipped |

依赖：1→2→3→4→5；6 依赖 1；7/8 依赖 1-3；9 依赖全部。
