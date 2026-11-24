# Design — RAGFlow 多站点知识库

完整设计见归档文档：`docs/superpowers/specs/2026-11-24-ragflow-multi-site-design.md`（批准版 v2，含 builder 审阅意见）。

要点：
- 表：`ragflow_sites(id,owner_id,name,base_url,api_key,is_shared,enabled)`；`knowledge_bases` 加 `site_id`，唯一约束 `(site_id,dataset_id)`。
- 站点路由独立 `APIRouter(prefix='/api/knowledge/sites')`，在 knowledge.router 之前注册（避免 `/{kb_id}` 吞 sites）。
- 下发：`RAGFLOW_SITES_B64` / `RAGFLOW_DATASET_SITES_B64`，base64(JSON)，key 用 site.id；`.env` chmod 600。
- MCP `retrieve`：按 dataset→site 分组请求，chunks 按 score 全局排序截 top_k；每站点业务错误写 site_errors。
- 丢弃重建：清空旧表数据、DDL 改结构（create_all 不 ALTER）。
