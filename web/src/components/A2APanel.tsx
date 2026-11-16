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
import Stack from "@mui/material/Stack";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  ApiError,
  createA2AEndpoint,
  deleteA2AEndpoint,
  listA2AEndpoints,
  type A2AEndpoint,
} from "@/lib/api";

/**
 * A2A 出站端点配置。
 *
 * 语义：这些是「该 Agent 可以调用的外部 Agent」。
 * 保存后写入 profile 的 config.yaml: a2a_agents。
 */
export function A2APanel({ agentId }: { agentId: number }) {
  const [items, setItems] = useState<A2AEndpoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(await listA2AEndpoints(agentId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
      setItems([]);
    }
  }, [agentId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function remove(id: number) {
    try {
      await deleteA2AEndpoint(agentId, id);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <Box>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Box sx={{ display: "flex", alignItems: "center", mb: 1.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
          该 Agent 可以调用的外部 Agent（A2A 协议）
        </Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
          添加端点
        </Button>
      </Box>

      {items === null ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={22} />
        </Box>
      ) : items.length === 0 ? (
        <Alert severity="info">还没有 A2A 端点。</Alert>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>名称</TableCell>
              <TableCell>URL</TableCell>
              <TableCell>能力标签</TableCell>
              <TableCell align="right">超时</TableCell>
              <TableCell align="center">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((e) => (
              <TableRow key={e.id} hover>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {e.name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <code style={{ fontSize: 12 }}>{e.url}</code>
                </TableCell>
                <TableCell>
                  {(e.capabilities ?? []).length ? (
                    (e.capabilities ?? []).map((c) => (
                      <Chip key={c} size="small" label={c} sx={{ mr: 0.5 }} variant="outlined" />
                    ))
                  ) : (
                    <Typography variant="caption" color="text.secondary">
                      —
                    </Typography>
                  )}
                </TableCell>
                <TableCell align="right">{e.timeout}s</TableCell>
                <TableCell align="center">
                  <IconButton
                    size="small"
                    aria-label="删除"
                    onClick={() => void remove(e.id)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <AddA2ADialog
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

function AddA2ADialog({
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
  const [url, setUrl] = useState("");
  const [caps, setCaps] = useState("");
  const [timeoutS, setTimeoutS] = useState("120");
  const [busy, setBusy] = useState(false);

  function reset() {
    setName("");
    setUrl("");
    setCaps("");
    setTimeoutS("120");
  }

  async function submit() {
    setBusy(true);
    try {
      const res = await createA2AEndpoint(agentId, {
        name: name.trim(),
        url: url.trim(),
        capabilities: caps
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        timeout: Number(timeoutS) || 120,
      });
      if (res.apply_error) {
        onError(`已保存到数据库，但写入 config.yaml 失败：${res.apply_error}`);
      }
      reset();
      await onCreated();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>添加 A2A 端点</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
            helperText="会成为 config.yaml 的 key，小写字母/数字/连字符"
          />
          <TextField
            label="URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            placeholder="http://peer-host:9900"
          />
          <TextField
            label="能力标签"
            value={caps}
            onChange={(e) => setCaps(e.target.value)}
            placeholder="web_search, research"
            helperText="逗号分隔。a2a_orchestrate 按能力路由，建议填写。"
          />
          <TextField
            label="超时（秒）"
            value={timeoutS}
            onChange={(e) => setTimeoutS(e.target.value)}
            type="number"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          取消
        </Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={busy || !name.trim() || !url.trim()}
        >
          {busy ? "保存中…" : "保存"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
