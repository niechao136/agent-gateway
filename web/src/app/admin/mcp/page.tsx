"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Grid from "@mui/material/Grid";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import {
  ApiError,
  createMCPServer,
  deleteMCPServer,
  listMCPServers,
  testMCPServer,
  updateMCPServer,
  type AuthType,
  type MCPServer,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, EmptyState, SkeletonList } from "@/components/Common";
import { AuthFields } from "@/components/AuthFields";

const TRANSPORTS: MCPServer["transport"][] = ["stdio", "sse", "http", "streamable_http"];
const AUTH_TYPES: AuthType[] = ["none", "bearer", "header", "query", "basic"];

interface FormState {
  name: string;
  description: string;
  transport: MCPServer["transport"];
  command: string;
  args: string;
  url: string;
  auth_type: AuthType;
  token: string;
  auth_name: string;
  is_shared: boolean;
  enabled: boolean;
}

const EMPTY: FormState = {
  name: "",
  description: "",
  transport: "stdio",
  command: "",
  args: "",
  url: "",
  auth_type: "none",
  token: "",
  auth_name: "",
  is_shared: false,
  enabled: true,
};

function McpInner() {
  const [rows, setRows] = useState<MCPServer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<MCPServer | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await listMCPServers());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY);
    setDialogOpen(true);
  }

  function openEdit(s: MCPServer) {
    setEditing(s);
    setForm({
      name: s.name,
      description: s.description ?? "",
      transport: s.transport,
      command: s.command ?? "",
      args: (s.args ?? []).join(" "),
      url: s.url ?? "",
      auth_type: s.auth_type,
      token: "", // 不回明文；留空 = 不更新
      auth_name: s.auth_name ?? "",
      is_shared: s.is_shared,
      enabled: s.enabled,
    });
    setDialogOpen(true);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        transport: form.transport,
        command: form.transport === "stdio" ? form.command.trim() : undefined,
        args: form.transport === "stdio" && form.args.trim() ? form.args.trim().split(/\s+/) : undefined,
        url: form.transport !== "stdio" ? form.url.trim() : undefined,
        auth_type: form.auth_type,
        token: form.token || undefined, // 留空 = 不更新
        auth_name: ["header", "query"].includes(form.auth_type) ? form.auth_name.trim() : undefined,
        is_shared: form.is_shared,
        enabled: form.enabled,
      };
      if (editing) {
        await updateMCPServer(editing.id, body);
        setOk("已保存并同步到绑定的 Agent");
      } else {
        await createMCPServer(body);
        setOk("已创建");
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center">
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          MCP 服务器
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          新建服务器
        </Button>
      </Stack>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {rows === null ? (
        <SkeletonList />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<AddIcon fontSize="inherit" />}
          title="还没有 MCP 服务器"
          hint="MCP 服务器是 Agent 可调用的外部工具来源；创建后在 Agent 编辑页绑定。"
        />
      ) : (
        <Grid container spacing={2}>
          {rows.map((s) => (
            <Grid key={s.id} size={{ xs: 12, sm: 6, lg: 4 }}>
              <Card>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle1" fontWeight={700} sx={{ flexGrow: 1 }}>
                      {s.name}
                    </Typography>
                    {s.is_shared ? <Chip size="small" label="共享" /> : null}
                    <Chip
                      size="small"
                      label={s.enabled ? "启用" : "停用"}
                      color={s.enabled ? "success" : "default"}
                      variant="outlined"
                    />
                  </Stack>
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                    {s.transport === "stdio" ? `stdio: ${s.command}` : s.url}
                  </Typography>
                  <Typography variant="caption" color="text.disabled">
                    鉴权: {s.auth_type}
                    {s.has_token ? "（已配置密钥）" : ""}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ pt: 1.5 }}>
                    <Button size="small" onClick={() => openEdit(s)}>
                      编辑
                    </Button>
                    <Button
                      size="small"
                      onClick={async () => {
                        try {
                          const r = await testMCPServer(s.id);
                          setOk(`测试: ${r.ok ? "通过" : "失败"}（${r.source}）`);
                        } catch (e) {
                          setError(e instanceof ApiError ? e.message : "测试失败");
                        }
                      }}
                    >
                      测试
                    </Button>
                    <Button size="small" color="error" onClick={() => setConfirmId(s.id)}>
                      删除
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "编辑 MCP 服务器" : "新建 MCP 服务器"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              select
              label="传输方式"
              value={form.transport}
              onChange={(e) =>
                setForm({ ...form, transport: e.target.value as MCPServer["transport"] })
              }
            >
              {TRANSPORTS.map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </TextField>
            {form.transport === "stdio" ? (
              <>
                <TextField
                  label="启动命令"
                  value={form.command}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  placeholder="npx"
                />
                <TextField
                  label="参数（空格分隔）"
                  value={form.args}
                  onChange={(e) => setForm({ ...form, args: e.target.value })}
                  placeholder="-y @modelcontextprotocol/server-xxx /path"
                />
              </>
            ) : (
              <TextField
                label="URL"
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                placeholder="https://..."
              />
            )}

            <AuthFields
              authType={form.auth_type}
              token={form.token}
              authName={form.auth_name}
              hasExistingToken={editing?.has_token ?? false}
              onChange={(patch) => setForm({ ...form, ...patch })}
              authTypes={AUTH_TYPES}
            />

            {form.is_shared ? null : (
              <Typography variant="caption" color="text.secondary">
                共享开关需管理员（创建后由管理员在编辑中开启）。
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={busy || !form.name.trim()}
            onClick={() => void submit()}
          >
            保存
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除 MCP 服务器"
        message="若仍被 Agent 绑定，需要确认后强制删除并解绑。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          try {
            await deleteMCPServer(confirmId, true);
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

export default function McpPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <McpInner />
      </AdminShell>
    </GuardedShell>
  );
}
