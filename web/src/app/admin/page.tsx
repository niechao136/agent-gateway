"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Box from "@mui/material/Box";
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
import EditIcon from "@mui/icons-material/Edit";
import {
  ApiError,
  createAgent,
  deleteAgent,
  listAllAgents,
  publishAgent,
  unpublishAgent,
  type Agent,
} from "@/lib/api";
import { GuardedShell } from "@/lib/authGuard";
import { AdminNav } from "@/components/AdminNav";

export default function AdminPage() {
  return (
    <GuardedShell require="admin">
      <AdminAgents />
    </GuardedShell>
  );
}

function AdminAgents() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      setAgents(await listAllAgents());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
      setAgents([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggle(a: Agent) {
    try {
      if (a.status === "published") await unpublishAgent(a.id);
      else await publishAgent(a.id);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  async function remove(a: Agent) {
    if (!confirm(`删除 Agent「${a.name}」？对应的 hermes profile 也会被删除。`)) return;
    try {
      await deleteAgent(a.id);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar>
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            管理中心
          </Typography>
          <AdminNav current="agents" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
          <Typography variant="h5" sx={{ fontWeight: 700, flexGrow: 1 }}>
            Agent 列表
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
            新建 Agent
          </Button>
        </Box>

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}

        {agents === null ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : agents.length === 0 ? (
          <Alert severity="info">还没有 Agent。点右上角「新建 Agent」开始。</Alert>
        ) : (
          <Table size="small" sx={{ bgcolor: "background.paper" }}>
            <TableHead>
              <TableRow>
                <TableCell>名称</TableCell>
                <TableCell>slug</TableCell>
                <TableCell>状态</TableCell>
                <TableCell>禁用工具组</TableCell>
                <TableCell>profile</TableCell>
                <TableCell align="right">操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {agents.map((a) => (
                <TableRow key={a.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {a.name}
                    </Typography>
                    {a.description ? (
                      <Typography variant="caption" color="text.secondary">
                        {a.description}
                      </Typography>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <code>{a.slug}</code>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={a.status === "published" ? "已发布" : "草稿"}
                      color={a.status === "published" ? "success" : "default"}
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {a.disabled_toolsets.length ? a.disabled_toolsets.join(", ") : "（全开）"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{a.profile_name}</Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => void toggle(a)}>
                      {a.status === "published" ? "下线" : "发布"}
                    </Button>
                    <IconButton
                      size="small"
                      aria-label="编辑"
                      onClick={() => router.push(`/admin/agents/${a.id}/edit`)}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                    <IconButton size="small" aria-label="删除" onClick={() => void remove(a)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Container>

      <CreateAgentDialog
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

function CreateAgentDialog({
  open,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  onError: (msg: string) => void;
}) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [soul, setSoul] = useState("");
  // v2：disabled_toolsets 直接编辑；空数组 = 全放开（谨慎），缺省由后端给只读助手默认集
  const [disabled, setDisabled] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  function reset() {
    setSlug("");
    setName("");
    setDescription("");
    setSoul("");
    setDisabled([]);
  }

  async function submit() {
    setBusy(true);
    try {
      await createAgent({
        slug: slug.trim(),
        name: name.trim(),
        description: description.trim() || undefined,
        soul: soul.trim() || undefined,
        // 前端不传 = 后端给只读助手默认集；传空数组 = 明确全开
        disabled_toolsets: disabled.length ? disabled : undefined,
      });
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
      <DialogTitle>新建 Agent</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
          <TextField
            label="slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            helperText="小写字母/数字/连字符，用于 URL。创建后不可改。"
          />
          <TextField
            label="描述"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            minRows={2}
          />
          <TextField
            label="System Prompt（SOUL.md）"
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            multiline
            minRows={4}
            helperText="留空则用「你是「{名称}」」的默认模板"
          />
          <TextField
            label="禁用的工具组（逗号分隔，留空 = 只读助手默认集）"
            value={disabled.join(", ")}
            onChange={(e) =>
              setDisabled(
                e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              )
            }
            helperText="例如 terminal, browser。留空使用安全的默认集（禁 terminal/file/browser 等）。"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          取消
        </Button>
        <Button variant="contained" onClick={() => void submit()} disabled={busy || !slug || !name}>
          {busy ? "创建中…" : "创建"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
