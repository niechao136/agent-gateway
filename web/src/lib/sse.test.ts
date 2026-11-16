import { describe, expect, it } from "vitest";
import { parseSSEBlock } from "./sse";

describe("parseSSEBlock", () => {
  it("解析 event + data", () => {
    const r = parseSSEBlock('event: token\ndata: {"content":"hi"}');
    expect(r).not.toBeNull();
    expect(r!.event).toBe("token");
    expect(r!.data).toBe('{"content":"hi"}');
  });

  it("跳过 keepalive 注释行", () => {
    expect(parseSSEBlock(": keepalive")).toBeNull();
  });

  it("块内混有 keepalive 时仍能解析", () => {
    const r = parseSSEBlock(': keepalive\nevent: token\ndata: {"content":"x"}');
    expect(r!.event).toBe("token");
    expect(r!.data).toBe('{"content":"x"}');
  });

  it("空块返回 null", () => {
    expect(parseSSEBlock("")).toBeNull();
  });

  it("只有 event 没有 data 返回 null", () => {
    expect(parseSSEBlock("event: token")).toBeNull();
  });

  it("多行 data 用换行拼接", () => {
    const r = parseSSEBlock("event: token\ndata: line1\ndata: line2");
    expect(r!.data).toBe("line1\nline2");
  });

  it("兼容 CRLF", () => {
    const r = parseSSEBlock('event: token\r\ndata: {"a":1}\r');
    expect(r!.event).toBe("token");
    expect(r!.data).toBe('{"a":1}');
  });

  it("data 冒号后的单个空格被剥离", () => {
    const r = parseSSEBlock("event: x\ndata:  two-spaces");
    expect(r!.data).toBe(" two-spaces");
  });

  it("未知事件类型也能解析出原始 data", () => {
    const r = parseSSEBlock("event: something\ndata: {}");
    expect(r!.event).toBe("something");
  });
});
