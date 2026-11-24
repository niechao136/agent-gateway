# RAGFlow 多站点知识库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans (native) or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「站点连接」与「知识库」拆成两层，支持同站点多库免重复配置、多站点不同密钥正确下发、api_key 脱敏可见、Agent 编辑页去重。

**Architecture:** 新增 `ragflow_sites` 表，`knowledge_bases` 加 `site_id` 并删除 `base_url/api_key`；profile `.env` 用 base64(JSON) 存站点表与 dataset→站点映射；内置 MCP `retrieve` 工具按映射分组请求各站点并聚合。控制层是配置编译器，MCP 是执行体。

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL；Next.js + MUI 9；Python stdlib MCP server（stdio JSON-RPC）

**Spec:** `docs/superpowers/specs/2026-11-24-ragflow-multi-site-design.md` (v2)

## Global Constraints
- 存量数据丢弃重建，**不写迁移脚本**。部署必须显式 `DROP TABLE agent_knowledge_bases, knowledge_bases CASCADE`，`ragflow_sites` 由 create_all 新建。
- 站点主键用 `site.id` 作 JSON key（不用 name，改名无需重下发）。
- 禁止转移站点 owner；`KnowledgeBase.owner_id` 仅冗余快照，权限以 `site.owner_id` 为准。
- api_key 明文只存 DB 与 profile `.env`（权限 600）；接口仅返回 `has_api_key` 与编辑详情里的掩码；日志/前端不得出现明文。
- FastAPI 依赖注入用默认参数风格 `x: T = Depends(...)`，避免嵌套 Annotated 递归。
- MUI 9 的 Stack/Typography 不接受 `alignItems`/`noWrap` 等 prop，一律走 `sx`。
- 站点路由用独立 `APIRouter` 且在 `main.py` 中先于 `knowledge.router` include。
- 编辑页两个知识库区块合并为一个，删除「需开 terminal / knowledge_search Skill」旧文案。

## Review Focus
- 同站点加第二个库：站点只配一次，第二库继承连接信息 → Task 3 测试。
- 多站点不同 key：两个站点 dataset 分别路由到正确 base_url/key → Task 5 测试。
- api_key 编辑时不回明文：`KbOut` 无明文，编辑详情仅掩码 → Task 3 测试。
- Agent 绑定状态可加载：`getAgentKnowledge` 返回数组，勾选正确回填 → Task 7 tsc/验证。
- 删除站点 force 级联后所有绑定 Agent 同步且不残留旧 key → Task 2 测试（同步在 Task 4 补全，Task 2 先用可 patch 的占位函数）。
- profile `.env` 密钥权限 600 → Task 5 测试。

---

### Task 1: 数据模型与清理脚本

**Files:**
- Modify: `control/app/models.py` (KnowledgeBase 区，约 442-470)
- Create: `control/app/hermes/rag_env.py`（base64 编解码 helper）
- Test: `control/tests/test_rag_env.py`

**Interfaces:**
- Produces: `RagflowSite` ORM (id/owner_id/name/base_url/api_key/is_shared/enabled)；`KnowledgeBase` 新增 `site_id`，删除 `base_url/api_key`，唯一约束 `(site_id, dataset_id)`；`rag_env.encode_sites(sites:dict, dataset_sites:dict)->tuple[str,str]` 与 `decode_sites(...)`。

- [ ] **Step 1: 写失败测试** `test_rag_env.py`：`encode_sites({"1":{"base_url":"http://a","api_key":"secret"}}, {"d1":"1"})` 返回两个 base64 串，`decode_sites` 往返一致；断言明文 secret 不直接出现在编码结果。
- [ ] **Step 2: 运行** `pytest tests/test_rag_env.py -v`，Expected: FAIL（模块不存在）。
- [ ] **Step 3: 改 models.py**：新增 RagflowSite（照 `KnowledgeBase` 的 owner/is_shared 模式，`UNIQUE(owner_id,name)`）；KnowledgeBase 删 `base_url/api_key`、加 `site_id ForeignKey("ragflow_sites.id", ondelete="CASCADE")`、唯一约束改 `(site_id, dataset_id)`；`owner_id` 保留。
- [ ] **Step 4: 写 rag_env.py**：`encode_sites`/`decode_sites`，`base64.b64encode(json.dumps(...).encode()).decode()`，解码失败返回空 dict。
- [ ] **Step 5: 运行测试** Expected: PASS。
- [ ] **Step 6: Commit** `feat: ragflow site model + base64 env helper`

### Task 2: 站点路由（独立 router）

**Files:**
- Modify: `control/app/routes/knowledge.py`（站点 schema/CRUD/test/datasets）
- Modify: `control/app/main.py`（先 include sites_router）
- Test: `control/tests/test_ragflow_sites.py`

**Interfaces:**
- Consumes: Task 1 `RagflowSite`。
- Produces: `sites_router = APIRouter(prefix="/api/knowledge/sites")`；`GET/POST /api/knowledge/sites`、`PATCH/DELETE /sites/{id}`（force 级联）、`POST /sites/{id}/test`、`GET /sites/{id}/datasets`；schema `SiteOut{id,name,base_url,has_api_key,is_shared,enabled}`、`SiteDetailOut(SiteOut + api_key_masked)`。

- [ ] **Step 1: 写失败测试**：建站点→列表返回 has_api_key=true 且无明文；PATCH 不改 owner；删被引用站点默认 409，force=200 且绑定清除；`/sites` 不被 `/{kb_id}` 吞（200 而非 422）。
- [ ] **Step 2: 运行** Expected: FAIL。
- [ ] **Step 3: 实现 sites_router**：CRUD 用 `session.commit()`+`refresh()`；掩码复用 `_mask` 风格 `key[:4]+"•••"`；POST test 用已保存 key 调 `_ragflow_datasets`；GET datasets 要求 `can_modify`。
- [ ] **Step 4: force 删站点**：删该站点所有 KnowledgeBase + 对应 AgentKnowledgeBase 行，收集受影响 agent_id，逐个重跑下发（下个 Task 的 `sync_agents_of_site`），错误进 `sync_errors`。
- [ ] **Step 5: main.py include sites_router 在 knowledge.router 之前**。
- [ ] **Step 6: 运行测试** Expected: PASS。
- [ ] **Step 7: Commit** `feat: ragflow site routes + force cascade`

### Task 3: 库路由改造 + 站点内新增

**Files:**
- Modify: `control/app/routes/knowledge.py`（KbIn/KbOut/create/update/list/delete）
- Test: `control/tests/test_ragflow_kb.py`

**Interfaces:**
- Consumes: Task 2 `SiteOut`、site 权限规则。
- Produces: `KbIn{site_id,name,dataset_id,dataset_name,description,is_shared,enabled}`；`KbOut` 增 `site_id/site_name/has_api_key`（无明文无掩码）；create 从 site 复制 owner_id；所有写触发 `_sync_agents_of_site`。

- [ ] **Step 1: 写失败测试**：同站点建两库只需两个 dataset_id；list 返回 site_name；他人站点下未共享库不可见；改库/删库触发同步（mock）。
- [ ] **Step 2: 运行** Expected: FAIL。
- [ ] **Step 3: 改 KbIn/KbOut/create**：删 base_url/api_key 字段，site_id 必填；create 校验 site 存在+可修改；owner_id=site.owner_id；name 必填（前端预填）。
- [ ] **Step 4: list 可见性**：`owner==me OR (kb.is_shared AND site.enabled)`；JOIN site 取 site_name。
- [ ] **Step 5: 更新/删除**：改/删后调 `_sync_agents_of_site`。
- [ ] **Step 6: 运行测试** Expected: PASS。
- [ ] **Step 7: Commit** `feat: knowledge base under site`

### Task 4: rag_sync 多站点下发

**Files:**
- Modify: `control/app/hermes/rag_sync.py`（`_write_env`/`apply_knowledge_tool`/`remove_knowledge_tool` 签名）
- Modify: `control/app/routes/knowledge.py`（`_sync_tool`/`_sync_agents_of_site` 组装 sites/dataset_sites 传入）
- Create: `control/tests/test_rag_sync_multisite.py`（改造 `test_knowledge_tool.py`）

**Interfaces:**
- Consumes: Task 1 `rag_env.encode_sites`；Task 3 KbOut。
- Produces: `apply_knowledge_tool(profile, *, sites:dict[str,dict], dataset_sites:dict[str,str]) -> dict`；`remove_knowledge_tool(profile)->dict`（签名不变，清全部 RAGFLOW_*）。

- [ ] **Step 1: 改测试**：`test_knowledge_tool.py` 断言从 `RAGFLOW_ALLOWED_DATASETS=d1,d2` 改为解码 `RAGFLOW_SITES_B64`/`RAGFLOW_DATASET_SITES_B64` 内容；新增 `.env` 文件权限 600 断言。
- [ ] **Step 2: 运行** Expected: FAIL。
- [ ] **Step 3: 实现**：`_write_env` 写 base64 两变量；写入后 `os.chmod(path, 0o600)`；`apply_knowledge_tool` 接收 sites/dataset_sites；空则清全部；`_sync_mcp_entry` 不变。
- [ ] **Step 4: `_sync_agents_of_site(session, site)`**：查该站点所有库→查绑定这些库的 agent→对每个 agent 组装 sites（所有已绑定库涉及的站点）/dataset_sites→调 apply。
- [ ] **Step 5: 运行测试** Expected: PASS。
- [ ] **Step 6: Commit** `feat: multi-site ragflow env sync`

### Task 5: MCP server 多站点路由

**Files:**
- Modify: `control/app/hermes/ragflow_mcp_server.py`
- Test: `control/tests/test_ragflow_multisite_mcp.py`

**Interfaces:**
- Consumes: Task 4 的 `RAGFLOW_SITES_B64`/`RAGFLOW_DATASET_SITES_B64`。
- Produces: `retrieve` 返回 `[{content,dataset_id,site_name,doc,score}]` 或 `{"site_errors":[...]}`。

- [ ] **Step 1: 写失败测试**：mock httpx，两个站点分别 key 不同，retrieve(dataset_ids=[d1,d2]) 发出两次带正确 Authorization 的请求，结果按 score 合并；站点返回 `code!=0` 时出现在 site_errors；未知 dataset_id 报错。
- [ ] **Step 2: 运行** Expected: FAIL。
- [ ] **Step 3: 实现**：读 b64 env→decode；dataset→site 映射分组；每站点 POST `{base_url}/api/v1/retrieval` body `{dataset_ids, question, page_size:top_k}`，header `Authorization: Bearer {key}`；业务码检查；合并按 score 降序截 top_k，无 score 用 index 稳定排序；保留旧单站点 env fallback 但优先级最低。
- [ ] **Step 4: 运行测试** Expected: PASS。
- [ ] **Step 5: Commit** `feat: ragflow MCP multi-site routing`

### Task 6: 连带修复（ingest + 测试）

**Files:**
- Modify: `control/app/task_runner.py`（delivery=knowledge 段，约 150-158）
- Test: `control/tests/test_rag_ingest.py`

**Interfaces:**
- Consumes: Task 3 `KnowledgeBase.site_id` + `RagflowSite`。
- Produces: ingest 从 join site 取 base_url/api_key。

- [ ] **Step 1: 写失败测试**：建 site+kb，task delivery=knowledge 触发 ingest，断言 POST 到 site.base_url 且带 site.api_key。
- [ ] **Step 2: 运行** Expected: FAIL（kb 无 base_url 属性）。
- [ ] **Step 3: 改 task_runner**：`select(KnowledgeBase, RagflowSite).join(RagflowSite, ...)` 取连接信息；kb 不存在时给出明确错误。
- [ ] **Step 4: 运行测试** Expected: PASS。
- [ ] **Step 5: 全量后端测试** Expected: 全绿。
- [ ] **Step 6: Commit** `fix: ragflow ingest multi-site + tests`

### Task 7: 前端 - api.ts 与知识库页

**Files:**
- Modify: `web/src/lib/api.ts`（KnowledgeBase/Site 类型 + 站点接口 + 修 getAgentKnowledge 返回类型）
- Modify: `web/src/app/admin/knowledge/page.tsx`（两区：站点管理 + 库管理）

**Interfaces:**
- Consumes: Task 2/3/4 API。
- Produces: `listRagflowSites/createRagflowSite/updateRagflowSite/deleteRagflowSite/testRagflowSite/listSiteDatasets`；`createKnowledgeBase(body:{site_id,...})`；`getAgentKnowledge(): Promise<KnowledgeBase[]>`（修 bug）。

- [ ] **Step 1: 改 api.ts 类型**：KnowledgeBase 加 site_id/site_name/has_api_key；新增 RagflowSite 接口与函数；`getAgentKnowledge` 改 `Promise<KnowledgeBase[]>`。
- [ ] **Step 2: 改 knowledge 页**：顶部「站点」区（卡片+新建/编辑 dialog，api_key 输入框 placeholder=留空不修改 + 掩码提示，测试/查看数据集按钮）；下部「知识库」区（新建用站点下拉→拉 dataset 下拉）。
- [ ] **Step 3: `npx tsc --noEmit`** Expected: 无错误。
- [ ] **Step 4: `npx vitest run` + `npx next build`** Expected: 全绿。
- [ ] **Step 5: Commit** `feat: knowledge UI site sections + api types`

### Task 8: 前端 - Agent 编辑页去重

**Files:**
- Modify: `web/src/app/admin/agents/[id]/edit/page.tsx`（tab===6 知识库区，约 623-687）

**Interfaces:**
- Consumes: Task 7 `getAgentKnowledge(): Promise<KnowledgeBase[]>`。

- [ ] **Step 1: 删除重复区块**：移除「绑定的知识库（RAGFlow）」旧 Card（约 623-647）或「知识库（RAGFlow）」旧 Card（约 649-687）之一；保留一个，按 site_name 分组展示勾选框。
- [ ] **Step 2: 修加载**：`kbBind` 现为数组，`setKnowledgeBound(kbBind.map(k=>k.id))`（不再 `.bound`）。
- [ ] **Step 3: 删旧文案**：彻底删除「knowledge_search 检索 Skill」「需要开启 terminal 工具集」文案，统一为「内置 MCP 检索工具」。
- [ ] **Step 4: tsc + vitest + next build** Expected: 全绿。
- [ ] **Step 5: Commit** `fix: agent knowledge tab dedupe + binding load`

### Task 9: 部署（丢弃重建）

**Files:** 无代码改动，仅服务器操作。

- [ ] **Step 1: 确认用户已同意丢弃数据**（已在设计确认）。
- [ ] **Step 2: 停 control**。
- [ ] **Step 3: PG 执行** `DROP TABLE IF EXISTS agent_knowledge_bases, knowledge_bases CASCADE;`（ragflow_sites 新表由 create_all 建；旧知识库记录/绑定全部丢弃）。
- [ ] **Step 4: 重建 control/web 镜像**（服务器默认 pip 源；内存紧张时分两次 build）。
- [ ] **Step 5: 启动**，create_all 建新表。
- [ ] **Step 6: profile 残留清理**：对含 ragflow-retrieve 的 profile 调一次 `remove_knowledge_tool()`，清旧 RAGFLOW_*（fallback 失效）。
- [ ] **Step 7: 端到端**：建站点（http://139.224.13.57 + key）→ 拉 3 个 dataset → 建 3 个库（同站点免重复填）→ 建 Agent 绑多库 → 提问验证检索 → 检查 `.env` 权限 600 → 确认日志无明文 key。
- [ ] **Step 8: Commit**（若有无代码变更）`chore: deploy ragflow multi-site`
