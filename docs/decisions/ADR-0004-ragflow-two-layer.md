# ADR-0004：RAGFlow 拆站点/库两层，检索保持 MCP

- 状态：Accepted（2026-11-24，见 [变更](../changes/2026-11-24-ragflow-multi-site/proposal.md)）

## 背景
原表把站点连接（base_url/api_key）和一个 dataset 揉在一条记录：同站点多库重复配置；key 脱敏过度看起来没保存；多站点不同 key 无法下发。

## 决策
- 拆 `ragflow_sites`（站点，配一次）与 `knowledge_bases`（库，dataset_id + site_id）。
- 多站点检索**保持 MCP**：profile `.env` 写 base64(JSON) 的站点映射 + dataset→站点映射；`ragflow_mcp_server` 工具内按站点分组请求、聚合结果、上报 site_errors。
- key 只返回 `has_api_key` + 掩码；`.env` 权限 600。

## 理由
跨站点路由是工具内部实现细节，不该推给模型；Skill 方案依赖 terminal 工具集，用户明确不要；MCP 是既有方向。

## 后果
- 支持一个 Agent 绑定多站点多库。
- 旧 profile 的 `RAGFLOW_ALLOWED_DATASETS` 仅作兼容 fallback。
