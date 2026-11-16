"""SSE 翻译：hermes 流 → 前端契约。

前端事件（与 a2a-gateway 保持一致，见 SPEC §1.3）：
    event: token      data: {"content": "..."}
    event: tool_start data: {"name": "..."}
    event: tool_end   data: {"name": "...", "output": "..."}
    event: interrupt  data: {"question": "..."}
    event: done       data: {"thread_id": "..."}
    event: error      data: {"detail": "..."}

★ hermes 的真实事件格式（实测抓包，见 SPEC §5.4）：

    event: run.started
    data: {"session_id":"...","run_id":"run_xxx","seq":1,...}

    event: message.started
    data: {"message":{"id":"msg_xxx","role":"assistant"},"seq":2}

    : keepalive                     ← 每 10s 无事件时发，必须跳过

    event: assistant.delta
    data: {"delta":"文本增量","message_id":"msg_xxx",...}

    event: assistant.completed
    data: {"content":"完整文本","completed":true,...}

    event: tool.progress
    data: {"tool_name":"web_search","delta":"...","message_id":"..."}

    event: run.failed / run.completed
    data: {...,"content":"..."}

注意：
- 事件名是扁平点号风格（`assistant.delta`），**不是** OpenAI 的 chat.completion.chunk
- 增量在顶层 `delta` 字段，**不是** choices[0].delta.content
- 请求体是 `{"message": "..."}`，**不是** `{"messages":[...]}`
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)


def sse(event: str, payload: dict[str, Any]) -> bytes:
    """构造一条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _is_comment(line: str) -> bool:
    """SSE 注释行（keepalive）：以 `:` 开头。必须跳过。"""
    return line.startswith(":")


def parse_sse_block(block: str) -> tuple[str | None, str | None]:
    """解析一个 SSE 块（已按空行切分）。

    返回 (event_name, data_str)；注释块返回 (None, None)。
    """
    event: str | None = None
    data_lines: list[str] = []

    for raw in block.splitlines():
        line = raw.rstrip("\r")
        if not line:
            continue
        if _is_comment(line):
            # keepalive —— 忽略，绝不能当数据
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())

    if not data_lines:
        return event, None
    return event, "\n".join(data_lines)


def _chunk_text(obj: dict) -> str | None:
    """从 chunk 中取增量文本。

    兼容两种形态：
    1. hermes 原生事件（实测）：{"delta": "...", ...} 事件名 assistant.delta
    2. OpenAI 兼容 chunk：{"choices":[{"delta":{"content":"..."}}]}
    """
    # hermes 原生
    delta = obj.get("delta")
    if isinstance(delta, str) and delta:
        return delta

    # OpenAI 风格
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    d = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(d, dict):
        return None
    content = d.get("content")
    return content if isinstance(content, str) and content else None


def _tool_event(obj: dict, event_name: str | None) -> tuple[str, str | None] | None:
    """识别工具进度事件，返回 (name, output_or_None)。

    hermes 形态（实测）：
        event: tool.progress
        {"tool_name": "web_search", "delta": "...", "message_id": "..."}
    以及 tool.started / tool.completed / tool.failed 事件类型。
    """
    name = obj.get("tool_name") or obj.get("tool") or obj.get("name")
    if not isinstance(name, str) or not name:
        return None

    phase = str(
        obj.get("event_type") or obj.get("phase") or obj.get("event") or event_name or ""
    ).lower()

    if "fail" in phase:
        return name, (obj.get("error") or "failed")
    if "complet" in phase or "end" in phase:
        out = obj.get("output") or obj.get("result") or obj.get("delta")
        return name, (str(out)[:2000] if out is not None else "")
    if "start" in phase:
        return name, None
    # tool.progress 的中间态：当作 start（前端显示"正在调用"）
    return name, None


async def translate_stream(
    raw_chunks: AsyncIterator[bytes],
    *,
    thread_id: str,
) -> AsyncIterator[bytes]:
    """把 hermes 的 SSE 字节流翻译成前端契约。"""
    buffer = ""
    emitted_any_token = False
    saw_terminal = False
    final_content = ""

    try:
        async for chunk in raw_chunks:
            buffer += chunk.decode("utf-8", errors="replace")

            # SSE 以空行分隔帧；同时兼容 \r\n\r\n
            while True:
                idx = buffer.find("\n\n")
                sep = 2
                crlf = buffer.find("\r\n\r\n")
                if crlf != -1 and (idx == -1 or crlf < idx):
                    idx, sep = crlf, 4
                if idx == -1:
                    break

                block, buffer = buffer[:idx], buffer[idx + sep :]
                event_name, data = parse_sse_block(block)
                if data is None:
                    continue  # 纯注释/心跳块

                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    if data.strip() not in ("[DONE]", "done"):
                        logger.debug("跳过非 JSON SSE 数据: %r", data[:120])
                    continue
                if not isinstance(obj, dict):
                    continue

                ev = (event_name or "").lower()

                # ── 工具进度 ──
                if "tool" in ev:
                    te = _tool_event(obj, event_name)
                    if te:
                        name, output = te
                        if output is None:
                            yield sse("tool_start", {"name": name})
                        else:
                            yield sse("tool_end", {"name": name, "output": output})
                        continue

                # ── 增量文本（assistant.delta）──
                text = _chunk_text(obj)
                if text and not ev.endswith(".completed"):
                    emitted_any_token = True
                    yield sse("token", {"content": text})
                    continue

                # ── 终态 ──
                if ev in ("assistant.completed", "run.completed", "run.failed"):
                    saw_terminal = True
                    content = obj.get("content")
                    if isinstance(content, str) and content:
                        final_content = content
                        # 若从未发过增量（非流式模型），把完整内容一次性发出
                        if not emitted_any_token:
                            emitted_any_token = True
                            yield sse("token", {"content": content})
                    if ev == "run.failed":
                        err = obj.get("error") or obj.get("reason") or "运行失败"
                        yield sse("error", {"detail": str(err)[:300]})
                        return
                    continue

                # run.started / message.started 等：忽略
                continue

        if not saw_terminal and not emitted_any_token:
            yield sse("error", {"detail": "对话未产生任何输出"})
            return

        yield sse("done", {"thread_id": thread_id})

    except Exception as exc:  # noqa: BLE001
        logger.exception("流式翻译失败")
        detail = f"对话处理失败: {exc}"[:200] if not emitted_any_token else "对话处理失败"
        yield sse("error", {"detail": detail})
