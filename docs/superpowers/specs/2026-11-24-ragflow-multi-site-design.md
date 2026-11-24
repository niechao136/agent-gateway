# RAGFlow 知识库：站点分层 + 多站点检索设计（v2）

日期：2026-11-24
状态：待批准（已纳入 builder 审阅意见）

## 背景与动机

当前 `knowledge_bases` 表把「RAGFlow 站点连接（base_url + api_key）」和「一个数据集（dataset_id）」揉在同一条记录里（一个实例 = 一个站点 + 一个库）。四个实际问题：

1. **重复配置**：同站点加第二个库要重复填 base_url/api_key。
2. **api_key 看起来没保存**：`KbOut` 完全不返回 key（连掩码都没有），前端编辑表单无法回填。
3. **多站点不可行**：`_sync_tool` 只把第一个库的 key 写进 profile `.env`，`ragflow_mcp_server` 无法知道哪个 dataset 属于哪个站点。
4. **Agent 编辑页重复区块**：`tab===6` 里「绑定的知识库（RAGFlow）」（约 623-647 行）与「知识库（RAGFlow）」（649-687 行）两块重复勾选区，且旧文案仍写「knowledge_search 检索 Skill」「需开启 terminal 工具集」，与当前内置 MCP 实现矛盾。

用户已确认的决策：
- 数据模型**拆两层**（站点 + 库）
- 多站点检索**保持 MCP 形式**，工具内部路由（理由：跨站点路由是工具实现细节，不该推给模型；且用户此前明确选择 MCP、不想依赖 terminal）
- 存量数据**丢弃重建**（不写迁移脚本）
- Agent 编辑页两块重复区合并

## 目标 / 非目标 / 反目标

**目标**
- 站点配置一次挂多个库；新增库无需重复填连接信息。
- 编辑库时能看见 key 是否已保存（掩码 + 布尔标志），改明文可选。
- 一个 Agent 可绑定**多站点多库**，`retrieve` 按 dataset→站点映射路由、聚合结果。
- Agent 编辑页「知识库」Tab 只有一个选择区，按站点分组展示。

**非目标**
- 不接入 RAGFlow 之外的来源；不改 toolset forcing 机制；不做文档切分/上传。

**反目标**
- 不把密钥明文写进 SKILL.md、config.yaml、前端、日志。
- 不让 Agent 跨 owner 访问他人站点/库。

## 方案（Approaches）

### 数据模型

```
RagflowSite（新表 ragflow_sites）
  id PK / owner_id FK / name String64 / base_url String512 / api_key String512(明文DB,接口掩码)
  is_shared / enabled / created_at / UNIQUE(owner_id, name)

KnowledgeBase（改造，注意见「部署」：需 DROP 重建）
  id PK / site_id FK ragflow_sites(新) / owner_id(保留冗余=site.owner,权限以site.owner为准)
  name String64(必填,前端预填 dataset_name) / source / description / dataset_id / dataset_name
  is_shared / enabled / created_at / UNIQUE(site_id, dataset_id)

AgentKnowledgeBase 绑定表不变（仍指向 KnowledgeBase.id）
```

**决策（builder 意见已纳入）**
- **站点 key 用 `site.id` 不用 name**：JSON 映射以数字 id 字符串为 key，改名不影响下发；`site_name` 只在 `KbOut` 展示。
- **禁止转移站点 owner**：PATCH site 不改 owner_id；`KnowledgeBase.owner_id` 只做冗余快照，权限一律以 `site.owner_id` 为准。
- **共享可见性**：他人可见的库 = 库 `is_shared=true` 且所属站点 `enabled=true`；站点 `is_shared` 仅控制「站点配置本身」是否在共享列表中可见，不代表其库自动可绑。
- **库 name 必填**：沿用 `KbIn.name(min_length=1)`，前端新建时预填 `dataset_name` 可编辑；不省略。

### API 改造

**路由冲突处理**：站点路由放**独立 `APIRouter(prefix="/api/knowledge/sites")`**，在 `main.py` 中于现有 `knowledge.router` 之前 include，避免 `/api/knowledge/{kb_id}` 把 "sites" 当 int 解析。

- `GET/POST /api/knowledge/sites` — 站点列表 / 新建（共享站点只返回脱敏字段）
- `PATCH/DELETE /api/knowledge/sites/{id}` — 更新/删除；被库引用默认 409，`?force=true` 时级联删除该站点全部库 + 所有 `agent_knowledge_bases` 绑定行，并**逐个受影响 Agent 重跑 `_sync_tool`**（失败逐条记录进响应 `sync_errors`，不静默吞）
- `POST /api/knowledge/sites/{id}/test` — 用已保存凭证测连通
- `GET /api/knowledge/sites/{id}/datasets` — 用已保存凭证拉 datasets（要求 `can_modify(user, site.owner_id)`，不能拿别人的 key 拉列表）
- `GET/POST/PATCH/DELETE /api/knowledge` — 库 CRUD，POST body 改为 `site_id + dataset_id + dataset_name + name`
- `KbOut` 增加 `site_id`/`site_name`/`has_api_key`；`api_key_masked` **只在编辑站点的详情接口返回**，库列表/站点列表不返回掩码，减少泄漏面
- `GET /knowledge/list-datasets`（临时凭据）保留供新建站点表单用；`POST /knowledge/{id}/test` 保留
- 库增删改、站点连接信息改 → 触发 `_sync_agents_of_site(session, site)`（抽出的统一同步函数）

### 下发机制（MCP 多站点路由）

profile `.env` 用 **base64(JSON)** 存（避免 dotenv 对引号/花括号解析差异，builder 确认此方向稳妥）：
```
RAGFLOW_SITES_B64=<base64 of {"1":{"base_url":"...","api_key":"..."},"2":{...}}>
RAGFLOW_DATASET_SITES_B64=<base64 of {"b9fc...":"1","35bc...":"2"}>
```
- 以 **site.id** 为 key；`enabled=false` 的站点与库不下发（不下发密钥）
- MCP server 启动 base64 解码；保留旧 `RAGFLOW_BASE_URL/API_KEY/ALLOWED_DATASETS` 的 fallback 仅为兼容旧 profile（新方案下不应存在，部署清理后失效）
- 「未传 dataset_ids 查所有已绑定库」= 查 `RAGFLOW_DATASET_SITES` 的全部 keys；**新加库必须重新下发**才生效（确认此为预期行为）

`ragflow_mcp_server.py`：
- `retrieve(question, dataset_ids=[], top_k=6)`
- 按 dataset→site 映射分组 → 每站点 POST `/api/v1/retrieval`（body `dataset_ids/question/page_size`）→ 合并 chunks 按 score 降序全局截 top_k → 返回 `[{content, dataset_id, site_name, doc, score}]`（保留现有 `doc`/`score` 字段名，新增 `site_name`）
- **每站点的业务错误码（HTTP 200 但 body `code!=0`，如免费版 403）作为 `site_errors` 一起返回给模型，不静默吞**
- dataset_id 不在映射 → 明确错误
- 无 score 时用 index 稳定排序

`rag_sync._write_env(profile, sites: dict, dataset_sites: dict)` 改签名（builder 指出旧签名硬编码 3 变量、返回计数常量要跟着改）；空绑定清全部 `RAGFLOW_*` 并移除 MCP 项。

### 连带修复（builder 发现，必须纳入）

1. **`getAgentKnowledge` 类型 bug**：api.ts:867 声明 `{bound:number[],effective:string[]}`，但后端 `GET /agents/{id}/knowledge` 实际返回 `list[KbOut]`；编辑页 `kbBind.bound ?? []` 运行时永远空 → 已绑定勾选状态加载不出来。改为 `Promise<KnowledgeBase[]>` + `kbBind.map(k=>k.id)`。
2. **`ragflow_ingest.py` 断链**：`task_runner.py` 的 `delivery=knowledge` 直接用 `kb.base_url/api_key`（拆表后字段没了）→ 改为 join `ragflow_sites` 取连接信息。清空表后定时任务里悬空的 `knowledge_id` 需前端提示重新选择。
3. **测试断言**：`test_knowledge_tool.py` 断言 `RAGFLOW_ALLOWED_DATASETS=d1,d2`，改为断言 `RAGFLOW_SITES_B64`/`RAGFLOW_DATASET_SITES_B64` 解码后内容。
4. **部署 DROP 重建**：`create_all` 不会 ALTER 已存在的 `knowledge_bases`（删列 + 加 site_id + 改唯一约束）→ 部署必须显式 `DROP TABLE knowledge_bases, agent_knowledge_bases CASCADE`，再由 create_all 重建；`ragflow_sites` 为新表自动建。
5. **profile 残留清理**：清库后对所有含 `ragflow-retrieve` 的 profile 触发一次 `remove_knowledge_tool()`，清掉旧 `RAGFLOW_*`（否则 fallback 仍暴露旧库）。
6. **.env 权限**：`RAGFLOW_SITES_B64` 含明文 key，profile `.env` 必须是 **600**（builder 指出 644 全局可读与反目标矛盾）；核对 `_atomic_write` 是否 chmod，必要时写入后显式 `os.chmod(path, 0o600)`。
7. **旧文案清除**：编辑页合并时连同「knowledge_search Skill」「需开启 terminal」旧文案一起删除，统一为「内置 MCP 检索工具」。

### 前端

- `/admin/knowledge` 上下两区：站点列表（卡片，测试/编辑/删除/查看数据集）+ 库列表（所属站点/dataset/状态）。新增库用站点下拉 + 拉取数据集下拉，无站点时 Alert 引导。
- Agent 编辑页「知识库」Tab 合并为一个区：按站点分组（站点名小标题），每组列该站点的库勾选框；删除重复区块与旧文案。
- api.ts 类型/接口随后端调整（`RagflowSite` 等）。

### 部署（丢弃重建）

1. 停 control；2. `DROP TABLE agent_knowledge_bases, knowledge_bases CASCADE`（`ragflow_sites` 新建由 create_all 建，旧库记录随之丢弃）；3. 重建 control/web 镜像；4. 启动后 create_all 建新表；5. 对已有 profile 跑一次 `remove_knowledge_tool()` 清残留；6. 用户在页面重新建站点 → 拉库 → 建库 → Agent 绑定。

## 测试计划
- 后端：站点 CRUD/权限/脱敏、库 CRUD 绑 site、用保存 key 拉 datasets、多站点 `.env` 下发/清理、MCP 多站点路由（mock HTTP）、业务错误码透传、api_key 不出现在响应/日志、`ragflow_ingest` 多站点取连接信息。
- 前端：修 `getAgentKnowledge` 类型后 tsc + next build + vitest。
- 部署：DROP 重建表 + profile 残留清理 + 真实 RAGFlow 三站点路由验证。

## 风险
- 清库会解除所有 Agent 的知识库绑定与定时任务里的 knowledge_id，需用户确认。
- MCP 多站点是 N+1 请求（每站点一次），top_k 全局聚合在工具内做；单站点失败以 site_errors 返回而非拖垮全部。
- `.env` base64 含明文 key，权限严格 600，不进日志/响应。
