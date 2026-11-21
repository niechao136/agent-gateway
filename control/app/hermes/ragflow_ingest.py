"""把文本写入 RAGFlow 知识库（供定时任务 delivery=knowledge 使用）。

RAGFlow API: POST /api/v1/datasets/{dataset_id}/documents
body: {"name": ..., "content": ...} （纯文本上传）
"""

from __future__ import annotations

import logging
import uuid

import httpx

logger = logging.getLogger(__name__)


async def ingest_text(kb, text: str) -> None:
    """把 text 作为一份新文档写入指定知识库。"""
    base = (kb.base_url or "").rstrip("/")
    if not base or not kb.api_key or not kb.dataset_id:
        raise RuntimeError("知识库连接信息不完整，无法写入")
    name = f"task-{uuid.uuid4().hex[:12]}.txt"
    url = f"{base}/api/v1/datasets/{kb.dataset_id}/documents"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            url,
            headers={"Authorization": "Bearer " + kb.api_key},
            json={"name": name, "content": text},
        )
        r.raise_for_status()
