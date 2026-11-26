"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Drawer from "@mui/material/Drawer";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Divider from "@mui/material/Divider";
import Tooltip from "@mui/material/Tooltip";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import MenuIcon from "@mui/icons-material/Menu";
import SendIcon from "@mui/icons-material/Send";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  ApiError,
  createConversation,
  deleteConversation,
  getMessages,
  getRole,
  listConversations,
  type Conversation,
} from "@/lib/api";
import { GuardedShell } from "@/lib/authGuard";
import { useColorMode } from "@/lib/theme";
import { ChangePasswordDialog } from "@/components/ChangePasswordDialog";
import { streamChat } from "@/lib/sse";
import type { ChatMessage } from "@/lib/chatTypes";
import { MessageBubble } from "@/components/MessageBubble";

export default function ChatPage() {
  return (
    <GuardedShell>
      <ChatView />
    </GuardedShell>
  );
}

function ChatView() {
  const router = useRouter();
  const { mode, toggle } = useColorMode();
  const isAdmin = getRole() === "admin";
  const [passwordOpen, setPasswordOpen] = useState(false);
  const params = useParams<{ slug: string; threadId?: string }>();
  const slug = params.slug;
  const urlThreadId = params.threadId ? Number(params.threadId) : null;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const toolSeqRef = useRef<number>(0);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations(slug));
    } catch {
      /* 列表失败不阻塞对话 */
    }
  }, [slug]);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  // URL 带 threadId 时自动打开该会话
  useEffect(() => {
    if (urlThreadId && Number.isFinite(urlThreadId) && urlThreadId > 0) {
      void selectConversation(urlThreadId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlThreadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function ensureConversation(first: string): Promise<number> {
    if (activeId) return activeId;
    const conv = await createConversation(slug, first);
    setActiveId(conv.id);
    setConversations((prev) => [conv, ...prev]);
    return conv.id;
  }

  /** 点击历史会话时加载消息（刷新页面后不丢对话）。 */
  async function selectConversation(id: number) {
    setActiveId(id);
    setDrawer(false);
    setMessages([]);
    setLoadingHistory(true);
    try {
      const history = await getMessages(id);
      setMessages(
        history.map((m) => ({
          id: m.id,
          role: (m.role as ChatMessage["role"]) ?? "assistant",
          content: m.content,
          toolName: m.toolName,
        })),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载历史失败");
    } finally {
      setLoadingHistory(false);
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;

    setError(null);
    setBusy(true);
    setInput("");
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: text }]);

    const assistantId = `a-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      const convId = await ensureConversation(text);
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      await streamChat(convId, text, {
        signal: ctrl.signal,
        onEvent: (ev) => {
          if (ev.type === "token") {
            setMessages((m) =>
              m.map((x) =>
                x.id === assistantId ? { ...x, content: x.content + ev.content } : x,
              ),
            );
          } else if (ev.type === "tool_start") {
            // 每个 tool 事件分配唯一序号，避免同名工具多次调用时回填错位
            toolSeqRef.current += 1;
            const seq = toolSeqRef.current;
            setMessages((m) => {
              // 工具步骤插到「助手回答」之前，保证视觉顺序：用户 → 工具 → 结论
              const idx = m.findIndex((x) => x.id === assistantId);
              const toolMsg: ChatMessage = {
                id: `t-${seq}`,
                role: "tool",
                toolName: ev.name,
                toolArgs: ev.args,
                toolSeq: seq,
                toolStatus: "running",
                content: "",
              };
              if (idx === -1) return [...m, toolMsg];
              return [...m.slice(0, idx), toolMsg, ...m.slice(idx)];
            });
          } else if (ev.type === "tool_end") {
            setMessages((m) => {
              // 按 name + running 状态匹配最早的一条（FIFO），精确回填
              for (let i = 0; i < m.length; i += 1) {
                if (
                  m[i].role === "tool" &&
                  m[i].toolName === ev.name &&
                  m[i].toolStatus === "running"
                ) {
                  const copy = [...m];
                  copy[i] = {
                    ...copy[i],
                    content: ev.output,
                    toolArgs: ev.args || copy[i].toolArgs,
                    toolStatus: "done",
                  };
                  return copy;
                }
              }
              return m;
            });
          } else if (ev.type === "error") {
            setMessages((m) => [
              ...m.map((x) => (x.id === assistantId ? { ...x, streaming: false } : x)),
              { id: `e-${Date.now()}`, role: "error", content: ev.detail },
            ]);
          } else if (ev.type === "done") {
            setMessages((m) =>
              m.map((x) => (x.id === assistantId ? { ...x, streaming: false } : x)),
            );
          }
        },
      });

      setMessages((m) =>
        m.map((x) => (x.id === assistantId ? { ...x, streaming: false } : x)),
      );
      void refreshConversations();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发送失败");
      setMessages((m) =>
        m.map((x) => (x.id === assistantId ? { ...x, streaming: false } : x)),
      );
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  async function removeConversation(id: number) {
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    } catch {
      setError("删除会话失败");
    }
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100dvh" }}>
      <AppBar
        position="static"
        color="inherit"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: "divider" }}
      >
        <Toolbar>
          <IconButton edge="start" onClick={() => router.push("/chat")} aria-label="返回">
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, flexGrow: 1, ml: 0.5 }}>
            {slug}
          </Typography>
          <Tooltip title={mode === "dark" ? "切换亮色" : "切换暗色"}>
            <IconButton onClick={toggle} size="small">
              {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>
          {isAdmin ? (
            <Tooltip title="管理中心">
              <IconButton onClick={() => router.push("/admin")} size="small">
                <AdminPanelSettingsIcon />
              </IconButton>
            </Tooltip>
          ) : null}
          <Tooltip title="修改密码">
            <IconButton onClick={() => setPasswordOpen(true)} size="small">
              <LockOutlinedIcon />
            </IconButton>
          </Tooltip>
          <IconButton onClick={() => setDrawer(true)} aria-label="会话列表">
            <MenuIcon />
          </IconButton>
        </Toolbar>
      </AppBar>

      <Box sx={{ flex: 1, overflowY: "auto", bgcolor: "background.default" }}>
        <Box sx={{ maxWidth: 820, mx: "auto", px: { xs: 1.5, sm: 2 }, py: 2 }}>
          {error ? (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
              {error}
            </Alert>
          ) : null}

          {loadingHistory ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
              <CircularProgress size={28} />
            </Box>
          ) : messages.length === 0 ? (
            <Box sx={{ textAlign: "center", py: 8, color: "text.secondary" }}>
              <Typography variant="body1">开始一段新对话</Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                输入消息后会创建会话
              </Typography>
            </Box>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}
          <div ref={bottomRef} />
        </Box>
      </Box>

      <Paper square elevation={0} sx={{ borderTop: 1, borderColor: "divider", p: 1.5 }}>
        <Box sx={{ maxWidth: 820, mx: "auto", display: "flex", gap: 1, alignItems: "flex-end" }}>
          <TextField
            multiline
            maxRows={6}
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            disabled={busy}
          />
          <Button
            variant="contained"
            onClick={() => void send()}
            disabled={busy || !input.trim()}
            sx={{ minWidth: 48, height: 40 }}
          >
            {busy ? <CircularProgress size={18} color="inherit" /> : <SendIcon fontSize="small" />}
          </Button>
        </Box>
      </Paper>

      <Drawer anchor="right" open={drawer} onClose={() => setDrawer(false)}>
        <Box sx={{ width: 300, display: "flex", flexDirection: "column", height: "100%" }}>
          <Toolbar sx={{ gap: 1 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, flexGrow: 1 }}>
              会话
            </Typography>
            <IconButton
              size="small"
              aria-label="新会话"
              onClick={() => {
                setActiveId(null);
                setMessages([]);
                setDrawer(false);
              }}
            >
              <AddIcon />
            </IconButton>
          </Toolbar>
          <Divider />
          <List sx={{ flex: 1, overflowY: "auto" }}>
            {conversations.length === 0 ? (
              <Box sx={{ p: 2, color: "text.secondary" }}>
                <Typography variant="body2">暂无会话</Typography>
              </Box>
            ) : (
              conversations.map((c) => (
                <ListItemButton
                  key={c.id}
                  selected={c.id === activeId}
                  onClick={() => void selectConversation(c.id)}
                >
                  <ListItemText
                    primary={c.title || "未命名会话"}
                    secondary={new Date(c.last_active_at).toLocaleString()}
                    slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }}
                  />
                  <IconButton
                    size="small"
                    edge="end"
                    aria-label="删除会话"
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeConversation(c.id);
                    }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </ListItemButton>
              ))
            )}
          </List>
        </Box>
      </Drawer>
      <ChangePasswordDialog
        open={passwordOpen}
        onClose={() => setPasswordOpen(false)}
      />
    </Box>
  );
}
