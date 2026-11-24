# ADR-0002：对外 API 采用 Messages 语义，不做 OpenAI 兼容

- 状态：Accepted（Batch 3）

## 背景
曾考虑提供 OpenAI-compatible `/v1/chat/completions`。

## 决策
对外 API 用 `/v1/agents/{slug}/messages`（Messages 语义）：请求体 `{message, conversation_id?}`。

## 理由
Agent 是有状态实体（profile / SOUL / skills / 会话归属），不是无状态 completion。OpenAI 格式无法表达这些，会误导调用方。

## 后果
- 优点：语义清晰；与 A2A Agent Card 的 skill 描述一致。
- 代价：不能直接用 OpenAI SDK 调用；需提供自己的接入文档。
