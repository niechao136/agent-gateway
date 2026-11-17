"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  ApiError,
  createConnector,
  deleteConnector,
  listAgents,
  listConnectors,
  platformCredentialFields,
  restartConnector,
  subscribeConnectorStatus,
  updateConnector,
  type Agent,
  type Connector,
  type ConnectorPlatform,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, EmptyState, SkeletonList, StatusDot } from "@/components/Common";

const PLATFORMS: ConnectorPlatform[] = ["telegram", "feishu", "slack"];

const FIELD_LABELS: Record<string, string> = {
  bot_token: "Bot Token",
  app_id: "App ID",
  app_secret: "App Secret",
  app_token: "App Token (xapp-)",
};

function ConnectorsInner() {
  const [rows, setRows] = useState<Connector[] | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{
    name: string;
    platform: ConnectorPlatform;
    agent_id: number | "";
    credentials: Record<string, string>;
  }>({ name: "", platform: "telegram", agent_id: "", credentials: {} });
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [cs, ags] = await Promise.all([
        listConnectors(),
        listAgents().catch(() => [] as Agent[]),
      ]);
      setRows(cs);
      setAgents(ags);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // SSE 实时状态（批次 4 决策）
  useEffect(() => {
    const unsub = subscribeConnectorStatus((list) => setRows(list));
    return unsub;
  }, []);

  const fields = useMemo(
    () => platformCredentialFields(form.platform),
    [form.platform],
  );

  async function submit() {
    try {
      await createConnector({
        name: form.name.trim(),
        platform: form.platform,
        agent_id: Number(form.agent_id),
        credentials: form.credentials,
        enabled: true,
      });
      setOpen(false);
      setForm({ name: "", platform: "telegram", agent_id: "", credentials: {} });
      setOk("已创建并启动长连接");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "创建失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          连接器
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
          新建连接器
        </Button>
      </Stack>

      <Typography variant="body2" color="text.secondary">
        长连接方式接入平台（无需公网域名与 webhook）。一个连接器绑定一个 Agent，每个外部会话独立。
      </Typography>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {rows === null ? (
        <SkeletonList />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<AddIcon fontSize="inherit" />}
          title="还没有连接器"
          hint="支持 Telegram（轮询）、飞书（WebSocket）、Slack（Socket Mode）。"
        />
      ) : (
        <Stack spacing={1}>
          {rows.map((c) => {
            const rt = c.runtime;
            return (
              <Card key={c.id}>
                <CardContent>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                    <StatusDot state={rt?.state ?? "idle"} />
                    <Typography sx={{ fontWeight: 700 }}>{c.name}</Typography>
                    <Chip size="small" label={c.platform} variant="outlined" />
                    <Chip size="small" label={`Agent: ${c.agent_slug ?? c.agent_id}`} variant="outlined" />
                    <Chip
                      size="small"
                      label={c.enabled ? "启用" : "停用"}
                      color={c.enabled ? "success" : "default"}
                      variant="outlined"
                    />
                    <Button
                      size="small"
                      startIcon={<RefreshIcon />}
                      onClick={async () => {
                        try {
                          await restartConnector(c.id);
                          setOk("已重连");
                          await load();
                        } catch (e) {
                          setError(e instanceof ApiError ? e.message : "重连失败");
                        }
                      }}
                    >
                      重连
                    </Button>
                    <Button
                      size="small"
                      onClick={async () => {
                        try {
                          await updateConnector(c.id, { enabled: !c.enabled });
                          await load();
                        } catch (e) {
                          setError(e instanceof ApiError ? e.message : "操作失败");
                        }
                      }}
                    >
                      {c.enabled ? "停用" : "启用"}
                    </Button>
                    <Button size="small" color="error" onClick={() => setConfirmId(c.id)}>
                      删除
                    </Button>
                  </Stack>
                  {rt?.last_error ? (
                    <Alert severity="error" sx={{ mt: 1 }}>
                      {rt.last_error}
                    </Alert>
                  ) : null}
                  <Typography variant="caption" color="text.disabled">
                    收 {rt?.messages_in ?? 0} / 发 {rt?.messages_out ?? 0}
                  </Typography>
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新建连接器</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              select
              label="平台"
              value={form.platform}
              onChange={(e) =>
                setForm({
                  ...form,
                  platform: e.target.value as ConnectorPlatform,
                  credentials: {},
                })
              }
            >
              {PLATFORMS.map((p) => (
                <MenuItem key={p} value={p}>
                  {p}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="绑定 Agent"
              value={form.agent_id}
              onChange={(e) =>
                setForm({ ...form, agent_id: e.target.value === "" ? "" : Number(e.target.value) })
              }
            >
              {agents.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.name}（{a.slug}）
                </MenuItem>
              ))}
            </TextField>
            {fields.map((f) => (
              <TextField
                key={f}
                label={FIELD_LABELS[f] ?? f}
                type={f.includes("secret") || f.includes("token") ? "password" : "text"}
                value={form.credentials[f] ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    credentials: { ...form.credentials, [f]: e.target.value },
                  })
                }
              />
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={
              !form.name.trim() ||
              form.agent_id === "" ||
              fields.some((f) => !form.credentials[f])
            }
            onClick={() => void submit()}
          >
            创建并启动
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除连接器"
        message="将停止长连接。已产生的会话记录保留。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          try {
            await deleteConnector(confirmId);
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

export default function ConnectorsPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <ConnectorsInner />
      </AdminShell>
    </GuardedShell>
  );
}
