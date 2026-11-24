# Proposal — RAGFlow 多站点知识库重构

## 目标
1. 站点配置一次挂多个库；新增库不重复填连接信息。
2. api_key 编辑可见（掩码 + 布尔），明文不留前端/日志。
3. Agent 可绑多站点多库，检索工具内部路由、聚合。
4. Agent 编辑页知识库区块去重。

## 范围
数据模型（站点/库两层）、knowledge 路由、rag_sync、ragflow_mcp_server、ragflow_ingest、前端 api.ts/知识库页/Agent 编辑页；告警：定时任务 knowledge 投递、profile 残留清理。

## 非目标
不接 RAGFlow 外来源；不改 toolset forcing；不做文档上传/切分。

## 验收
- 新增/列表/测试/删除站点与库全链路通过。
- 多站点绑定后 profile `.env` 含 base64 配置、权限 600。
- `retrieve` 按 dataset 路由到正确站点，业务错误进 site_errors。
- 编辑页只有一个知识库区块、显示站点分组。
- 后端全量测试 + 前端 tsc/build 通过。
