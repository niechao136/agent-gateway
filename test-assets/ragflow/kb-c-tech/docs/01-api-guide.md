# agent-gateway 对外 API 技术说明

文档编号：TECH-API-V1。

## 对外消息接口

- 端点：`POST /api/v1/agents/{slug}/messages`
- 鉴权：`Authorization: Bearer agk_xxx`（Agent API Key）
- 语义：Messages 语义，**不是** OpenAI 兼容格式。
- 请求体：`{"message": "...", "session_id": "...", "stream": false}`
- 限流：每个 Key **60 次/分钟**，超限返回 429 + Retry-After。

## API Key

- 格式：`agk_` + 32 位 hex。
- 按 Agent 隔离，Key 只能调用自己所属的 Agent。
- 明文仅在创建时返回一次，之后只显示前 8 位前缀。
- 仅 Agent owner 或管理员可创建/删除。

## A2A 服务端

- Agent Card：`GET /a2a/{slug}/.well-known/agent-card.json`
- JSON-RPC：`POST /a2a/{slug}`
- 支持方法：`message/send`、`message/stream`（含 v0.3 别名 `SendMessage`、`SendStreamingMessage`）。
- 鉴权：`X-Api-Key` 或 `Authorization: Bearer`。
- 仅**已发布**的 Agent 可被 A2A 调用。
