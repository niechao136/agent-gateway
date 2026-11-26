/** 复制文本到剪贴板；HTTP 非安全上下文下 navigator.clipboard 不可用，回退到 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  // 安全上下文优先用现代 API
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* 继续走 fallback */
    }
  }
  // HTTP 回退：临时 textarea + execCommand('copy')
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.setAttribute("data-clipboard", "1");
  Object.assign(ta.style, {
    position: "fixed",
    top: "-1000px",
    left: "-1000px",
    opacity: "0",
  });
  document.body.appendChild(ta);
  try {
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    return ok;
  } catch {
    return false;
  } finally {
    document.body.removeChild(ta);
  }
}
