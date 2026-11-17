/**
 * SSE 客户端：解析控制层的流式对话。
 *
 * 控制层事件契约（见 SPEC §1.3）：
 *   event: token      {"content": "..."}
 *   event: tool_start {"name": "..."}
 *   event: tool_end   {"name": "...", "output": "..."}
 *   event: interrupt  {"question": "..."}
 *   event: done       {"thread_id": "..."}
 *   event: error      {"detail": "..."}
 *
 * ★ 后端已经过滤了 hermes 的 keepalive，但这里仍按 SSE 规范跳过以 `:` 开头的
 *   注释行——防止将来中间层（nginx 等）注入心跳时前端崩溃。
 */

export type ChatEvent =
  | { type: "token"; content: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_end"; name: string; output: string }
  | { type: "interrupt"; question: string }
  | { type: "done"; thread_id: string }
  | { type: "error"; detail: string };

export interface StreamHandlers {
  onEvent: (ev: ChatEvent) => void;
  signal?: AbortSignal;
}

/** 解析单个 SSE 块（已按空行切分）。注释块返回 null。 */
export function parseSSEBlock(block: string): { event: string | null; data: string | null } | null {
  let event: string | null = null;
  const dataLines: string[] = [];
  let sawAnything = false;

  for (const raw of block.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (!line) continue;
    // SSE 注释/心跳：以 `:` 开头
    if (line.startsWith(":")) continue;
    sawAnything = true;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (!sawAnything || dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

function toChatEvent(event: string | null, raw: string): ChatEvent | null {
  let obj: Record<string, unknown>;
  try {
    obj = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }

  switch (event) {
    case "token":
      return typeof obj.content === "string" ? { type: "token", content: obj.content } : null;
    case "tool_start":
      return typeof obj.name === "string" ? { type: "tool_start", name: obj.name } : null;
    case "tool_end":
      return typeof obj.name === "string"
        ? { type: "tool_end", name: obj.name, output: String(obj.output ?? "") }
        : null;
    case "interrupt":
      return typeof obj.question === "string"
        ? { type: "interrupt", question: obj.question }
        : null;
    case "done":
      return { type: "done", thread_id: String(obj.thread_id ?? "") };
    case "error":
      return { type: "error", detail: String(obj.detail ?? "未知错误") };
    default:
      return null;
  }
}

/**
 * 发起流式对话并逐事件回调。
 *
 * 用 fetch + ReadableStream 而非 EventSource：EventSource 不支持 POST 与自定义头。
 */
export async function streamChat(
  conversationId: number,
  message: string,
  handlers: StreamHandlers,
): Promise<void> {
  const { onEvent, signal } = handlers;
  const token = localStorage.getItem("ag_token");

  const res = await fetch(`/api/chat/conversations/${conversationId}/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message }),
    signal,
  });

  if (res.status === 401) {
    localStorage.removeItem("ag_token");
    localStorage.removeItem("ag_user");
    location.href = "/login";
    return;
  }

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      const b = (await res.json()) as { detail?: string };
      if (b.detail) detail = b.detail;
    } catch {
      /* ignore */
    }
    onEvent({ type: "error", detail });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // 按空行切分完整帧，兼容 \r\n\r\n
      for (;;) {
        let idx = buffer.indexOf("\n\n");
        let sep = 2;
        const crlf = buffer.indexOf("\r\n\r\n");
        if (crlf !== -1 && (idx === -1 || crlf < idx)) {
          idx = crlf;
          sep = 4;
        }
        if (idx === -1) break;

        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + sep);

        const parsed = parseSSEBlock(block);
        if (!parsed) continue; // 注释/心跳块

        const ev = toChatEvent(parsed.event, parsed.data!);
        if (ev) onEvent(ev);
      }
    }
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    onEvent({ type: "error", detail: (err as Error).message });
  } finally {
    reader.releaseLock();
  }
}
