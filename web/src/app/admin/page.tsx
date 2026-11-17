"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActions from "@mui/material/CardActions";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import {
  ApiError,
  createAgent,
  listAgents,
  publishAgent,
  unpublishAgent,
  type Agent,
} from "@/lib/api";
import { ConfirmDialog, EmptyState, SkeletonList } from "@/components/Common";
import { GuardedShell } from "@/lib/authGuard";
import { AdminShell } from "@/components/AdminShell";

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; color: "success" | "default" }> = {
    published: { label: "已发布", color: "success" },
    draft: { label: "草稿", color: "default" },
  };
  const c = map[status] ?? { label: status, color: "default" as const };
  return <Chip size="small" label={c.label} color={c.color} variant="outlined" />;
}

function AgentsInner() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [form, setForm] = useState({ slug: "", name: "", description: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAgents(await listAgents());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitCreate() {
    setBusy(true);
    try {
      const a = await createAgent({
        slug: form.slug.trim(),
        name: form.name.trim(),
        description: form.description.trim() || undefined,
      });
      setCreateOpen(false);
      setForm({ slug: "", name: "", description: "" });
      router.push(`/admin/agents/${a.id}/edit`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function togglePublish(a: Agent) {
    try {
      if (a.status === "published") await unpublishAgent(a.id);
      else await publishAgent(a.id);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Agent
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          新建 Agent
        </Button>
      </Stack>

      {error ? <Typography color="error">{error}</Typography> : null}

      {agents === null ? (
        <SkeletonList rows={3} />
      ) : agents.length === 0 ? (
        <EmptyState
          icon={<SmartToyIcon fontSize="inherit" />}
          title="还没有 Agent"
          hint="创建第一个 Agent：命名、配置人格与工具，发布后即可对话。"
          action={
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              新建 Agent
            </Button>
          }
        />
      ) : (
        <Grid container spacing={2}>
          {agents.map((a) => (
            <Grid key={a.id} size={{ xs: 12, sm: 6, lg: 4 }}>
              <Card sx={{ height: "100%" }}>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle1" fontWeight={700} sx={{ flexGrow: 1, noWrap: true }}>
                      {a.name}
                    </Typography>
                    <StatusChip status={a.status} />
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1, minHeight: 32 }}>
                    {a.description || "（无描述）"}
                  </Typography>
                  <Typography variant="caption" color="text.disabled" sx={{ fontFamily: "monospace" }}>
                    {a.profile_name}
                  </Typography>
                </CardContent>
                <CardActions>
                  <Button size="small" onClick={() => router.push(`/admin/agents/${a.id}/edit`)}>
                    编辑
                  </Button>
                  <Button size="small" onClick={() => router.push(`/chat/${a.slug}`)}>
                    对话
                  </Button>
                  <Box sx={{ flexGrow: 1 }} />
                  <Button size="small" onClick={() => void togglePublish(a)}>
                    {a.status === "published" ? "取消发布" : "发布"}
                  </Button>
                  <Button size="small" color="error" onClick={() => setConfirmId(a.id)}>
                    删除
                  </Button>
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* 新建对话框 */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新建 Agent</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="slug（URL 标识）"
              value={form.slug}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              helperText="小写字母数字连字符，全局唯一"
            />
            <TextField
              label="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              label="描述"
              multiline
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <Typography variant="caption" color="text.secondary">
              创建后进入编辑页配置人格、工具与模型。默认启用安全的只读助手工具预设。
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={busy || !form.slug.trim() || !form.name.trim()}
            onClick={() => void submitCreate()}
          >
            创建
          </Button>
        </DialogActions>
      </Dialog>

      {/* 删除确认 */}
      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除 Agent"
        message="将删除 profile 与全部会话数据，不可恢复。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          const { deleteAgent } = await import("@/lib/api");
          try {
            await deleteAgent(confirmId);
            await load();
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "删除失败");
          }
        }}
        onClose={() => setConfirmId(null)}
      />
    </Stack>
  );
}

export default function AdminAgentsPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <AgentsInner />
      </AdminShell>
    </GuardedShell>
  );
}
