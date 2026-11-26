"use client";

import { useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/lib/chatTypes";

/** 尝试把工具输出格式化为可读文本；JSON 会缩进，便于阅读。 */
function formatToolOutput(raw: string): { text: string; isJson: boolean } {
  if (!raw) return { text: "", isJson: false };
  try {
    const parsed = JSON.parse(raw);
    return { text: JSON.stringify(parsed, null, 2), isJson: true };
  } catch {
    // hermes 的 tool 输出可能是 Python repr（单引号），尝试温和转换
    return { text: raw, isJson: false };
  }
}

function ToolCallBlock({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const running = message.toolStatus === "running";
  const { text, isJson } = formatToolOutput(message.content);
  const preview = text.length > 160 ? `${text.slice(0, 160)}…` : text;

  return (
    <Box
      sx={{
        display: "inline-block",
        maxWidth: "100%",
        bgcolor: "action.hover",
        border: 1,
        borderColor: "divider",
        borderRadius: 2,
        px: 1.25,
        py: 0.75,
        mb: 1,
      }}
    >
      <StackRow>
        {running ? <CircularProgress size={14} /> : null}
        <Chip
          size="small"
          label={`${running ? "调用中" : "工具"} · ${message.toolName ?? "tool"}`}
          color={running ? "primary" : "default"}
          variant="outlined"
          onClick={() => setExpanded((v) => !v)}
          sx={{ cursor: "pointer" }}
        />
      </StackRow>
      {expanded && message.toolArgs ? (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 0.75,
            p: 1,
            maxHeight: 120,
            overflow: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            bgcolor: "action.selected",
            borderRadius: 1,
            fontFamily: "ui-monospace, monospace",
            fontSize: 11,
            opacity: 0.85,
          }}
        >
          {`参数: ${message.toolArgs}`}
        </Box>
      ) : null}
      {text && expanded ? (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 0.75,
            p: 1,
            maxHeight: 260,
            overflow: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            bgcolor: "background.paper",
            borderRadius: 1,
            fontFamily: isJson ? "ui-monospace, monospace" : "inherit",
            fontSize: 12,
          }}
        >
          {text}
        </Box>
      ) : text ? (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          {preview}
        </Typography>
      ) : expanded ? (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5, whiteSpace: "pre-wrap" }}>
          该工具未返回可展示输出
        </Typography>
      ) : running ? (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          正在执行…
        </Typography>
      ) : null}
    </Box>
  );
}

/** 轻量行容器（避免引入 Stack 的 MUI9 prop 坑） */
function StackRow({ children }: { children: ReactNode }) {
  return <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>{children}</Box>;
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <Box sx={{ display: "flex", justifyContent: "flex-end", mb: 2 }}>
        <Paper
          elevation={0}
          sx={{
            px: 2,
            py: 1.25,
            maxWidth: "80%",
            bgcolor: "primary.main",
            color: "primary.contrastText",
            borderRadius: 3,
            borderTopRightRadius: 0.5,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          <Typography variant="body1" component="div">
            {message.content}
          </Typography>
        </Paper>
      </Box>
    );
  }

  const isError = message.role === "error";

  return (
    <Box sx={{ display: "flex", justifyContent: "flex-start", mb: 2 }}>
      <Paper
        elevation={0}
        sx={{
          px: 2,
          py: 1.25,
          maxWidth: "85%",
          bgcolor: isError ? "error.50" : "background.paper",
          border: 1,
          borderColor: isError ? "error.200" : "divider",
          borderRadius: 3,
          borderTopLeftRadius: 0.5,
          wordBreak: "break-word",
          "& p": { my: 0.5 },
          "& pre": {
            bgcolor: "#0f172a",
            color: "#e2e8f0",
            p: 1.5,
            borderRadius: 2,
            overflowX: "auto",
            fontSize: 13,
          },
          "& code": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13 },
          "& table": { borderCollapse: "collapse", width: "100%", my: 1 },
          "& th, & td": { border: 1, borderColor: "divider", px: 1, py: 0.5 },
        }}
      >
        {message.role === "tool" ? (
          <ToolCallBlock message={message} />
        ) : isError ? (
          <Typography variant="body2" color="error.main">
            {message.content}
          </Typography>
        ) : (
          <Box sx={{ typography: "body1" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </Box>
        )}
      </Paper>
    </Box>
  );
}
