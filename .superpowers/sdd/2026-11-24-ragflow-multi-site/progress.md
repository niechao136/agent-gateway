# SDD ledger — plan: docs/superpowers/plans/2026-11-24-ragflow-multi-site.md
# Pre-flight
Ruling: 在 master 直接实施 — 项目历史全在 master 且部署基于 master — 代价: 回退需 git revert
Task 2 -> Task 3: 站点路由产出 site CRUD，库路由消费 site_id — 无冲突（外键在 Task 1 建好）
Task 3 -> Task 4: 库路由调用 apply_knowledge_tool(profile, sites, dataset_sites) — 签名在 Task 4 定义，Task 3 用占位 patch 验证 — Ruling: Task 3 定义函数存根(stub)，Task 4 填实现 — 代价: Task 3 期间多站点下发是 no-op，但单测用 patch 覆盖
Task 4 -> Task 5: rag_sync 下发 RAGFLOW_*_B64，MCP server 消费 — 格式(base64 JSON + site.id key)在 spec 定死，一致
Task 6 -> Task 8: ingest 改 join site，前端 knowledge_id 语义不变 — 一致
Task 1 Step 1-2: RED verified — ModuleNotFoundError app.hermes.rag_env (expected, feature missing)
Task 1 GREEN: test_rag_env 3 passed. RagflowSite model added, KnowledgeBase.site_id, rag_env encode/decode.
Task 2 GREEN: 6 passed 1 skipped. ragflow_sites router registered before knowledge router. Force-delete cascade stub (Task 4 fills sync).
Task 3 GREEN: 8 passed 1 skipped. KB routes now site_id-based, owner=site.owner, _sync_tool builds multi-site payload (Task 4 will make apply_knowledge_tool accept it).
