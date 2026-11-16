import { describe, expect, it } from "vitest";

/**
 * SSE 流式解析的集成测试：验证端到端的帧切分与事件映射。
 * 这里复刻 sse.ts 里 streamChat 的解析循环，用字符串喂入。
 */
type ChatEvent =
  | { type: "token"; content: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_end"; name: string; output: string }
  | { type: "interrupt"; question: string }
  | { type: "done"; thread_id: string }
  | { type: "error"; detail: string };

function parseBlock(block: string): { event: string | null; data: string | null } | null {
  let event: string | null = null;
  const dataLines: string[] = [];
  let sawAnything = false;
  for (const raw of block.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (!line) continue;
    if (line.startsWith(":")) continue;
    sawAnything = true;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
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
    case "done":
      return { type: "done", thread_id: String(obj.thread_id ?? "") };
    case "error":
      return { type: "error", detail: String(obj.detail ?? "未知错误") };
    default:
      return null;
  }
}

/** 模拟流式喂入：按任意字节边界切分也要正确解析 */
function consume(chunks: string[]): ChatEvent[] {
  const out: ChatEvent[] = [];
  let buffer = "";
  for (const chunk of chunks) {
    buffer += chunk;
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
      const parsed = parseBlock(block);
      if (!parsed) continue;
      const ev = toChatEvent(parsed.event, parsed.data!);
      if (ev) out.push(ev);
    }
  }
  return out;
}

describe("SSE 流式解析", () => {
  it("逐 token 事件按序产出", () => {
    const raw =
      'event: token\ndata: {"content":"你"}\n\n' +
      'event: token\ndata: {"content":"好"}\n\n' +
      'event: done\ndata: {"thread_id":"s1"}\n\n';
    const evs = consume([raw]);
    expect(evs).toHaveLength(3);
    expect(evs[0]).toEqual({ type: "token", content: "你" });
    expect(evs[1]).toEqual({ type: "token", content: "好" });
    expect(evs[2]).toEqual({ type: "done", thread_id: "s1" });
  });

  it("被任意切分（跨帧边界）仍能解析", () => {
    const raw =
      'event: token\ndata: {"content":"AB"}\n\n' + 'event: done\ndata: {"thread_id":"t"}\n\n';
    // 按 3 字符切
    const chunks: string[] = [];
    for (let i = 0; i < raw.length; i += 3) chunks.push(raw.slice(i, i + 3));
    const evs = consume(chunks);
    expect(evs[0]).toEqual({ type: "token", content: "AB" });
    expect(evs[1]).toEqual({ type: "done", thread_id: "t" });
  });

  it("keepalive 不会产生事件", () => {
    const raw =
      ": keepalive\n\n" +
      'event: token\ndata: {"content":"x"}\n\n' +
      ": keepalive\n\n";
    const evs = consume([raw]);
    expect(evs).toHaveLength(1);
    expect(evs[0].type).toBe("token");
  });

  it("工具事件正确映射", () => {
    const raw =
      'event: tool_start\ndata: {"name":"web_search"}\n\n' +
      'event: tool_end\ndata: {"name":"web_search","output":"3 results"}\n\n';
    const evs = consume([raw]);
    expect(evs[0]).toEqual({ type: "tool_start", name: "web_search" });
    expect(evs[1]).toEqual({ type: "tool_end", name: "web_search", output: "3 results" });
  });

  it("error 事件带 detail", () => {
    const evs = consume(['event: error\ndata: {"detail":"模型不可用"}\n\n']);
    expect(evs[0]).toEqual({ type: "error", detail: "模型不可用" });
  });

  it("非法 JSON 被跳过而不是崩溃", () => {
    const raw = 'event: token\ndata: not-json\n\n' + 'event: token\ndata: {"content":"ok"}\n\n';
    const evs = consume([raw]);
    expect(evs).toHaveLength(1);
    expect(evs[0]).toEqual({ type: "token", content: "ok" });
  });

  it("未知事件类型被忽略", () => {
    const evs = consume(['event: run.started\ndata: {"seq":1}\n\n']);
    expect(evs).toHaveLength(0);
  });

  it("CRLF 分隔的流也能解析", () => {
    const evs = consume(['event: token\r\ndata: {"content":"X"}\r\n\r\n']);
    expect(evs[0]).toEqual({ type: "token", content: "X" });
  });
});
