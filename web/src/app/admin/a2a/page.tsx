"use client";

import { useCallback, useEffect, useState } from "react";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import TestIcon from "@mui/icons-material/CheckCircle";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  ApiError,
  createA2AEndpoint,
  deleteA2AEndpoint,
  getA2AInbound,
  listA2AEndpoints,
  listPublishedAgents,
  pingA2AInbound,
  testA2AEndpoint,
  updateA2AEndpoint,
  type A2AEndpoint,
  type Agent,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { AuthFields } from "@/components/AuthFields";
import { ConfirmDialog, EmptyState, SkeletonList } from "@/components/Common";

const AUTH_TYPES = ["none", "bearer", "header", "query", "basic"] as const;

interface Form {
  name: string;
  description: string;
  url: string;
  target_type: "external" | "internal";
  target_agent_id: number | null;
  timeout: string;
  auth_type: (typeof AUTH_TYPES)[number];
  token: string;
  auth_name: string;
}

const EMPTY: Form = {
  name: "",
  description: "",
  url: "",
  target_type: "external",
  target_agent_id: null,
  timeout: "120",
  auth_type: "none",
  token: "",
  auth_name: "",
};

function A2aInner() {
  const [endpoints, setEndpoints] = useState<A2AEndpoint[] | null>(null);
  const [inbound, setInbound] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<A2AEndpoint | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);

  const load = useCallback(async () => {
    try {
      const [eps, ib, ags] = await Promise.all([
        listA2AEndpoints(),
        getA2AInbound().catch(() => null),
        listPublishedAgents().catch(() => []),
      ]);
      setAgents(ags);
      setEndpoints(eps);
      setInbound(ib as Record<string, unknown> | null);
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

  async function testEndpoint(e: A2AEndpoint) {
    setOk(null); setError(null);
    try {
      const r = await testA2AEndpoint(e.id);
      if (r.ok) setOk(`连接正常: ${r.name || e.name} (${r.url || e.url})`);
      else setError(`连接失败: ${r.message || "未知原因"}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "测试失败");
    }
  }

  function openEdit(e: A2AEndpoint) {
    setEditing(e);
    setForm({
      name: e.name,
      description: e.description ?? "",
      url: e.url,
      target_type: e.target_type,
      target_agent_id: e.target_agent_id,
      timeout: String(e.timeout),
      auth_type: e.auth_type,
      token: "",
      auth_name: e.auth_name ?? "",
    });
    setDialogOpen(true);
  }

  async function submit() {
    try {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        url: form.url.trim(),
        target_type: form.target_type,
        target_agent_id: form.target_type === "internal" ? form.target_agent_id : null,
        timeout: Number(form.timeout) || 120,
        auth_type: form.auth_type,
        token: form.token || undefined,
        auth_name: ["header", "query"].includes(form.auth_type) ? form.auth_name.trim() : undefined,
      };
      if (editing) await updateA2AEndpoint(editing.id, body);
      else await createA2AEndpoint(body);
      setDialogOpen(false);
      setOk("已保存并同步到绑定的 Agent");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          A2A
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          新建出站端点
        </Button>
      </Stack>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {/* 1. 入站状态 */}
      <Card>
        <CardContent>
          <Stack direction="row" sx={{alignItems: "center",  mb: 1 }}>
            <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
              入站状态
            </Typography>
            <Button
              size="small"
              onClick={async () => {
                try {
                  await pingA2AInbound();
                  await load();
                  setOk("入站探测已执行");
                } catch (e) {
                  setError(e instanceof ApiError ? e.message : "探测失败");
                }
              }}
            >
              探测
            </Button>
          </Stack>
          {inbound === null ? (
            <Typography variant="body2" color="text.secondary">
              入站状态不可用（hermes 未运行或 A2A 未启用）。
            </Typography>
          ) : (
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {Object.entries(inbound)
                .filter(([k]) => !k.startsWith("_"))
                .slice(0, 8)
                .map(([k, v]) => (
                  <Chip
                    key={k}
                    size="small"
                    label={`${k}: ${typeof v === "boolean" ? (v ? "✓" : "✗") : String(v).slice(0, 30)}`}
                    variant="outlined"
                  />
                ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      {/* 2. 出站端点 */}
      <Typography variant="h6">出站端点</Typography>
      {endpoints === null ? (
        <SkeletonList />
      ) : endpoints.length === 0 ? (
        <EmptyState
          icon={<AddIcon fontSize="inherit" />}
          title="还没有出站端点"
          hint="出站端点是本平台 Agent 调用其他 Agent 的目标地址；在 Agent 编辑页绑定到具体 Agent。"
        />
      ) : (
        <Stack spacing={1}>
          {endpoints.map((e) => (
            <Card key={e.id}>
              <CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography sx={{ fontWeight: 700 }}>{e.name}</Typography>
                  {e.is_shared ? <Chip size="small" label="共享" /> : null}
                  <Chip
                    size="small"
                    label={e.enabled ? "启用" : "停用"}
                    color={e.enabled ? "success" : "default"}
                    variant="outlined"
                  />
                  <Chip size="small" label={`鉴权: ${e.auth_type}`} variant="outlined" />
                  <Button size="small" startIcon={<TestIcon />} onClick={async () => {
                    try {
                      const r = await testA2AEndpoint(e.id);
                      setOk(r.ok ? `连通: ${r.name || r.url}` : `失败: ${r.message}`);
                    } catch (err) { setError(err instanceof ApiError ? err.message : "测试失败"); }
                  }} sx={{ ml: "auto" }}>
                    测试
                  </Button>
                  <Button size="small" onClick={() => openEdit(e)}>
                    编辑
                  </Button>
                  <Button size="small" color="error" onClick={() => setConfirmId(e.id)}>
                    删除
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {e.url} · timeout {e.timeout}s
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}

      {/* 3. 使用说明 */}
      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography>使用说明</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" color="text.secondary" component="div">
            <div>· 入站：其他平台的 Agent 通过 A2A 协议调用本平台的 Agent（hermes 负责协议端点）。</div>
            <div>· 出站：在 Agent 编辑页把端点绑定到 Agent，配置会写入该 profile 的 config.yaml: a2a_agents 段。</div>
            <div>· 鉴权支持 none / bearer / header / query / basic 五种方式。</div>
            <div>· 端点修改后自动同步到所有绑定的 Agent。</div>
          </Typography>
        </AccordionDetails>
      </Accordion>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "编辑出站端点" : "新建出站端点"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <FormControl fullWidth>
              <InputLabel>目标类型</InputLabel>
              <Select
                value={form.target_type}
                label="目标类型"
                onChange={(e) => {
                  const t = e.target.value as "external" | "internal";
                  setForm({ ...form, target_type: t, target_agent_id: null, url: "" });
                }}
              >
                <MenuItem value="external">外部 A2A 服务</MenuItem>
                <MenuItem value="internal">本平台 Agent（内部互调）</MenuItem>
              </Select>
            </FormControl>
            {form.target_type === "internal" ? (
              <FormControl fullWidth>
                <InputLabel>目标 Agent（须已发布）</InputLabel>
                <Select
                  value={form.target_agent_id ?? ""}
                  label="目标 Agent（须已发布）"
                  onChange={(e) => {
                    const aid = Number(e.target.value);
                    const a = agents.find((x) => x.id === aid);
                    setForm({
                      ...form,
                      target_agent_id: aid,
                      name: form.name || (a ? `内部-${a.name}` : ""),
                      url: a ? `/a2a/${a.slug}` : "",  // 内部端点 URL 自动生成，只读展示
                    });
                  }}
                >
                  {agents.map((a) => (
                    <MenuItem key={a.id} value={a.id}>{a.name}（{a.slug}）</MenuItem>
                  ))}
                </Select>
              </FormControl>
            ) : null}
            <TextField
              label="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              label="URL"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              placeholder={form.target_type === "internal" ? "选择内部 Agent 后自动生成" : "http://host:port"}
              disabled={form.target_type === "internal"}
            />
            <TextField
              label="超时（秒）"
              type="number"
              value={form.timeout}
              onChange={(e) => setForm({ ...form, timeout: e.target.value })}
            />
            <Divider />
            <AuthFields
              authType={form.auth_type}
              token={form.token}
              authName={form.auth_name}
              hasExistingToken={editing?.has_token ?? false}
              authTypes={AUTH_TYPES}
              onChange={(patch) => setForm({ ...form, ...patch })}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>取消</Button>
          <Button variant="contained" disabled={!form.name.trim() || (form.target_type === "external" ? !form.url.trim() : !form.target_agent_id)} onClick={() => void submit()}>
            保存
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除出站端点"
        message="若仍被 Agent 绑定，将确认后强制删除并解绑。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          try {
            await deleteA2AEndpoint(confirmId, true);
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

export default function A2APage() {
  return (
    <GuardedShell>
      <AdminShell>
        <A2aInner />
      </AdminShell>
    </GuardedShell>
  );
}
