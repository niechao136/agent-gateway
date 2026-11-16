"use client";

import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Tooltip from "@mui/material/Tooltip";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import {
  ApiError,
  addMCP,
  deleteMCP,
  listMCP,
  testMCP,
  toggleMCP,
  type MCPServer,
} from "@/lib/api";

/**
 * MCP 服务器配置。
 *
 * 语义：这些服务器提供的工具会挂到该 Agent 上。
 * 保存后写入 profile 的 config.yaml: mcp_servers。
 *
 * ⚠️ 对 public 档位的 Agent 要注意工具数量：接 Cloudflare 那种 3300 工具的
 * 服务器会撑爆上下文。hermes 支持 tools.include / exclude 收窄（此处未暴露）。
 */
export function MCPPanel({ agentId }: { agentId: number }) {
  const [servers, setServers] = useState<MCPServer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r = await listMCP(agentId);
      setServers(r.servers);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
      setServers([]);
    }
  }, [agentId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function remove(name: string) {
    try {
      await deleteMCP(agentId, name);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  async function toggle(s: MCPServer) {
    try {
      await toggleMCP(agentId, s.name, !s.enabled);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "切换失败");
    }
  }

  async function test(s: MCPServer) {
    setTesting(s.name);
    setInfo(null);
    try {
      const r = await testMCP(agentId, s.name);
      const ok = (r as { ok?: boolean }).ok;
      const toolCount = (r as { tools?: unknown[] }).tools?.length;
      setInfo(
        ok === false
          ? `${s.name} 连接失败：${JSON.stringify(r).slice(0, 200)}`
          : `${s.name} 连接成功${toolCount != null ? `，发现 ${toolCount} 个工具` : ""}`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "测试失败");
    } finally {
      setTesting(null);
    }
  }

  return (
    <Box>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}
      {info ? (
        <Alert severity="info" sx={{ mb: 2 }} onClose={() => setInfo(null)}>
          {info}
        </Alert>
      ) : null}

      <Box sx={{ display: "flex", alignItems: "center", mb: 1.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
          该 Agent 可用的 MCP 服务器
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
          添加服务器
        </Button>
      </Box>

      {servers === null ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={22} />
        </Box>
      ) : servers.length === 0 ? (
        <Alert severity="info">还没有 MCP 服务器。</Alert>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>名称</TableCell>
              <TableCell>传输</TableCell>
              <TableCell>目标</TableCell>
              <TableCell>来源</TableCell>
              <TableCell align="center">启用</TableCell>
              <TableCell align="center">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {servers.map((s) => (
              <TableRow key={s.name} hover>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {s.name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip size="small" label={s.transport} variant="outlined" />
                </TableCell>
                <TableCell>
                  <code style={{ fontSize: 12 }}>
                    {s.transport === "stdio"
                      ? [s.command, ...(s.args ?? [])].filter(Boolean).join(" ")
                      : (s.url ?? "—")}
                  </code>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" color="text.secondary">
                    {s.plugin ? `插件 ${s.plugin}` : (s.source ?? "—")}
                  </Typography>
                </TableCell>
                <TableCell align="center">
                  <Switch
                    size="small"
                    checked={s.enabled}
                    onChange={() => void toggle(s)}
                    slotProps={{ input: { "aria-label": `启用 ${s.name}` } }}
                  />
                </TableCell>
                <TableCell align="center">
                  <Tooltip title="测试连接">
                    <IconButton
                      size="small"
                      onClick={() => void test(s)}
                      disabled={testing === s.name}
                    >
                      {testing === s.name ? (
                        <CircularProgress size={16} />
                      ) : (
                        <PlayArrowIcon fontSize="small" />
                      )}
                    </IconButton>
                  </Tooltip>
                  <IconButton size="small" aria-label="删除" onClick={() => void remove(s.name)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <AddMCPDialog
        agentId={agentId}
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          setOpen(false);
          await reload();
        }}
        onError={setError}
      />
    </Box>
  );
}

function AddMCPDialog({
  agentId,
  open,
  onClose,
  onCreated,
  onError,
}: {
  agentId: number;
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  onError: (m: string) => void;
}) {
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  function reset() {
    setName("");
    setCommand("");
    setArgs("");
    setUrl("");
    setTransport("stdio");
  }

  async function submit() {
    setBusy(true);
    try {
      await addMCP(agentId, {
        name: name.trim(),
        transport,
        ...(transport === "stdio"
          ? {
              command: command.trim(),
              args: args
                .split(/\s+/)
                .map((s) => s.trim())
                .filter(Boolean),
            }
          : { url: url.trim() }),
      });
      reset();
      await onCreated();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "添加失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>添加 MCP 服务器</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
            helperText="会成为 config.yaml 的 key"
          />
          <TextField
            select
            label="传输方式"
            value={transport}
            onChange={(e) => setTransport(e.target.value)}
          >
            <MenuItem value="stdio">stdio（本地命令）</MenuItem>
            <MenuItem value="sse">sse（HTTP 长连接）</MenuItem>
            <MenuItem value="streamable_http">streamable_http</MenuItem>
            <MenuItem value="http">http</MenuItem>
          </TextField>

          {transport === "stdio" ? (
            <>
              <TextField
                label="命令"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                required
                placeholder="npx"
              />
              <TextField
                label="参数"
                value={args}
                onChange={(e) => setArgs(e.target.value)}
                placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                helperText="空格分隔"
              />
            </>
          ) : (
            <TextField
              label="URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder="https://mcp.example.com/sse"
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          取消
        </Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={
            busy ||
            !name.trim() ||
            (transport === "stdio" ? !command.trim() : !url.trim())
          }
        >
          {busy ? "添加中…" : "添加"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
