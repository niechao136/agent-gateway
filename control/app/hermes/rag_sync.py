"""知识库检索 Skill 落地：把绑定的 RAGFlow 知识库生成一个 skill 写入 Agent profile。

目录：<data_root>/profiles/<profile>/skills/knowledge_search/
    ├── SKILL.md          检索技能说明（告诉模型何时/如何检索）
    └── scripts/
        └── retrieve.py   调用 RAGFlow /api/v1/retrieval 的脚本（需 terminal）

RAGFlow 检索 API（v1）：
    POST {base_url}/api/v1/retrieval
    Authorization: Bearer {api_key}
    body: {"dataset_ids": [...], "question": "...", "top_k": N}
    resp: {"data": {"chunks": [{"content": "...", "docnm_kwd": "...", "similarity": ...}]}}

bundle 里的脚本从环境变量取连接信息，避免把 api_key 明文写进 skill 文件；
连接信息由控制层在 profile 的 .env 里注入 RAGFLOW_BASE_URL / RAGFLOW_API_KEY / RAGFLOW_DATASET_IDS。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .a2a import _atomic_write
from .skill_sync import profile_skills_dir

logger = logging.getLogger(__name__)

SKILL_NAME = "knowledge_search"

SKILL_MD = """---
name: knowledge_search
description: 从绑定的知识库（RAGFlow）检索资料来回答用户问题。当用户询问内部文档、知识库内容、具体资料细节，或需要基于给定资料作答时，必须使用此技能。
metadata:
  hermes:
    requires_toolsets: [terminal]
---

# 知识库检索

本 Agent 绑定了外部知识库。回答涉及知识库内容的问题时：

1. 先用 `python3 {base}/scripts/retrieve.py "<用户问题>"` 检索（脚本会读取 profile .env 中的 RAGFLOW_* 配置）。
2. 脚本输出 JSON，包含 `chunks`（命中的文档片段，含 content / docnm_kwd / similarity）。
3. 基于检索到的片段作答，并标注来源文档名。
4. 若检索无结果或脚本报错，如实告知用户知识库中未找到相关内容，不要编造。

注意：一般常识性问题不需要检索；只有明确涉及知识库/内部资料时才用。
""".replace("{base}", "scripts")

RETRIEVE_PY = '''#!/usr/bin/env python3
"""RAGFlow 知识库检索。用法: python3 retrieve.py "问题" [--top-k 5]"""
import os, sys, json, urllib.request, urllib.error

def main():
    args = sys.argv[1:]
    top_k = 5
    if "--top-k" in args:
        i = args.index("--top-k")
        top_k = int(args[i + 1]); del args[i:i + 2]
    question = " ".join(args).strip()
    if not question:
        print(json.dumps({"error": "请提供检索问题"}, ensure_ascii=False)); return

    base = os.environ.get("RAGFLOW_BASE_URL", "").rstrip("/")
    key = os.environ.get("RAGFLOW_API_KEY", "")
    ids = [x for x in os.environ.get("RAGFLOW_DATASET_IDS", "").split(",") if x]
    if not base or not key or not ids:
        print(json.dumps({"error": "知识库未配置完整（base/key/dataset_ids）"}, ensure_ascii=False)); return

    body = json.dumps({"dataset_ids": ids, "question": question, "top_k": top_k}).encode()
    req = urllib.request.Request(
        base + "/api/v1/retrieval", data=body, method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        chunks = (data.get("data") or {}).get("chunks") or []
        out = [
            {"content": c.get("content", ""), "doc": c.get("docnm_kwd", ""),
             "score": c.get("similarity")}
            for c in chunks
        ]
        print(json.dumps({"chunks": out}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
'''


class RagSyncError(Exception):
    pass


def apply_knowledge_skill(
    profile: str,
    data_root: str,
    *,
    base_url: str,
    api_key: str,
    dataset_ids: list[str],
) -> dict:
    """生成一个检索 skill 到 profile，并把连接信息注入 profile .env。"""
    try:
        skill_dir = profile_skills_dir(profile, data_root) / SKILL_NAME
        scripts = skill_dir / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        _atomic_write(skill_dir / "SKILL.md", SKILL_MD)
        _atomic_write(scripts / "retrieve.py", RETRIEVE_PY)

        # 注入连接信息到 profile .env（幂等覆盖三行）
        env_path = Path(data_root) / ("config.env" if profile == "default" else f"profiles/{profile}/.env")
        lines: list[str] = []
        if env_path.exists():
            lines = [
                ln for ln in env_path.read_text(encoding="utf-8").splitlines()
                if not ln.startswith(("RAGFLOW_BASE_URL=", "RAGFLOW_API_KEY=", "RAGFLOW_DATASET_IDS="))
            ]
        lines += [
            f"RAGFLOW_BASE_URL={base_url}",
            f"RAGFLOW_API_KEY={api_key}",
            "RAGFLOW_DATASET_IDS=" + ",".join(dataset_ids),
        ]
        _atomic_write(env_path, "\n".join(lines) + "\n")
        return {"skill": SKILL_NAME, "path": str(skill_dir)}
    except (OSError, ValueError) as exc:
        raise RagSyncError(str(exc)) from exc


def remove_knowledge_skill(profile: str, data_root: str) -> dict:
    """解绑最后一个知识库时移除检索 skill 及 .env 中的 RAGFLOW_* 行。"""
    import shutil

    skill_dir = profile_skills_dir(profile, data_root) / SKILL_NAME
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    env_path = Path(data_root) / ("config.env" if profile == "default" else f"profiles/{profile}/.env")
    if env_path.exists():
        lines = [
            ln for ln in env_path.read_text(encoding="utf-8").splitlines()
            if not ln.startswith("RAGFLOW_")
        ]
        _atomic_write(env_path, "\n".join(lines) + ("\n" if lines else ""))
    return {"skill": SKILL_NAME, "removed": True}
