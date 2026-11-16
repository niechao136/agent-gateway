"use client";

import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/lib/chatTypes";

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
        {message.toolName ? (
          <Chip
            size="small"
            label={`工具：${message.toolName}`}
            color={message.role === "tool" ? "default" : "primary"}
            variant="outlined"
            sx={{ mb: 1 }}
          />
        ) : null}

        {isError ? (
          <Typography variant="body2" color="error.main">
            {message.content}
          </Typography>
        ) : message.role === "tool" ? (
          <Typography
            variant="body2"
            color="text.secondary"
            component="pre"
            sx={{ whiteSpace: "pre-wrap", fontFamily: "inherit", m: 0 }}
          >
            {message.content || "（无输出）"}
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
