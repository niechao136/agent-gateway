# RAGFlow 知识库测试资源包

用于验证 agent-gateway 的 RAGFlow 知识库检索能力：检索正确性、多知识库 `dataset_ids` 路由、端到端对话体验。

## 目录结构

```
ragflow/
├── README.md                         本说明
├── kb-a-company/                     知识库 A：公司制度
│   ├── docs/
│   │   ├── 01-expense-policy.md      报销制度（事实点：800元/30天/周三/50000元）
│   │   └── 02-leave-policy.md        考勤休假（事实点：年假15/20/25天、婚假10天）
│   └── questions/test-questions.md   应命中/不应命中/路由测试问题
├── kb-b-product/                     知识库 B：星笔记产品手册
│   ├── docs/
│   │   ├── 01-product-guide.md       功能与套餐（事实点：3个笔记本/29元/E1002）
│   │   └── 02-troubleshooting.md     错误码（E1001-E2003、附件100MB）
│   └── questions/test-questions.md
├── kb-c-tech/                        知识库 C：技术 FAQ
│   ├── docs/
│   │   ├── 01-api-guide.md           对外API（/v1/messages、限流60、agk_格式）
│   │   └── 02-deployment-faq.md      部署排障（9119/8642/1002:1003）
│   └── questions/test-questions.md
└── agent/kb-assistant-SOUL.md        知识库助手系统提示词（主动检索+路由+不编造）
```

## 设计说明

三个知识库主题完全隔离、每个文档含醒目的**人造事实点**（具体数字/错误码/路径），便于精确判断检索是否命中、是否产生幻觉：

| 库 | 主题 | 代表事实点 |
|---|---|---|
| KB-A | 公司制度 | 住宿上限 800 元、年假 15/20/25 天、打款周三 |
| KB-B | 产品手册 | E1002=手机号未注册、专业版 29 元/月、附件 100MB |
| KB-C | 技术 FAQ | 限流 60 次/分、dashboard 9119、a2a 需 platform_toolsets |

## 使用步骤

### 1. 在 RAGFlow 建库并上传文档（你来操作，需 RAGFlow 地址 + API Key）

1. 登录 RAGFlow → 新建 3 个 knowledge base，建议命名：
   - `kb-a-company`（公司制度）
   - `kb-b-product`（产品手册）
   - `kb-c-tech`（技术 FAQ）
2. 每个库上传对应 `docs/` 下的 Markdown 文件。
3. 等待文档解析/嵌入完成（RAGFlow 里状态变为完成）。
4. 记录 3 个 dataset 的 **id**（RAGFlow 库详情页或 API `GET /api/v1/datasets` 可查）。

### 2. 在 agent-gateway 登记知识库

进入「知识库」页 `/admin/knowledge`，新建 3 条记录：
- 名称：与 RAGFlow 一致（如 `kb-a-company`）
- Base URL：你的 RAGFlow 服务地址（如 `http://ragflow:9380`）
- API Key：RAGFlow 的 API Key
- Dataset ID：上一步记录的 id

每条建完点「测试」验证连通性（应返回 ok + dataset 列表）。

### 3. 新建知识库 Agent 并绑定

1. 新建 Agent（如 slug=`kb-assistant`）。

2. **「工具」Tab**：知识库工具是内置 MCP（`ragflow-retrieve`），绑定知识库后会自动启用，无需手动开 terminal。

3. **「知识库」Tab**：勾选 3 个知识库（一对多绑定）。

4. **「基本」Tab**：把 `agent/kb-assistant-SOUL.md` 的内容填入 soul 字段。

5. 发布 Agent。

### 4. 验证（按 questions/test-questions.md 逐条问）

**检索正确性**：问"一线城市住宿上限多少" → 应答 800 元并标注来源。

**多库路由**：
- 问"E1002 是什么意思" → 应答"手机号未注册"（从 KB-B）。
- 问"报销上限和年假天数" → 只从 KB-A 检索，不混入其他库。

**幻觉测试**：问"公司股票代码是多少" → 应答"知识库没有相关信息"，不得编造。

**端到端体验**：连续追问（"年假多少天？" → "那病假呢？"），验证会话连续 + 每次都检索。

## 预期工具调用

对话 stream 中应看到 `retrieve` 工具调用（经 SSE 翻译为 `tool_start`/`tool_end`）。若只看到 `tool_search` 而无 `retrieve`，说明知识库 MCP 未绑定成功或工具集未启用，检查：
- profile 的 `config.yaml` 中 `mcp.servers` 是否含 `ragflow-retrieve`
- profile 的 `.env` 是否有 `RAGFLOW_ALLOWED_DATASETS` 和连接信息

## 注意

- 本资源包只含源文件，未导入系统；知识库文档需你手动上传到 RAGFlow。
- 文档中的公司名"星海科技有限公司"、产品"星笔记"均为虚构，事实点仅用于测试。
