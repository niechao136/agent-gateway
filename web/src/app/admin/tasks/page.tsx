"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import HistoryIcon from "@mui/icons-material/History";
import { AdminShell } from "@/components/AdminShell";
import { EmptyState, SkeletonList } from "@/components/Common";
import { GuardedShell } from "@/lib/authGuard";
import {
  ApiError, DELIVERY_LABELS, createTask, deleteTask, listA2AEndpoints, listAgents,
  listConnectors, listKnowledgeBases, listTaskRuns, listTasks, runTaskNow, updateTask,
  type ScheduledTask, type TaskRunInfo,
} from "@/lib/api";

const EMPTY = {
  name: "", enabled: true, schedule_kind: "interval", every_seconds: "3600",
  cron_expr: "", action_type: "agent_message", target_agent_id: "" as number | "",
  a2a_endpoint_id: "" as number | "", payload: "", delivery: "log",
  webhook_url: "", connector_id: "" as number | "", knowledge_id: "" as number | "",
};

type Form = typeof EMPTY;

export default function TasksPage() {
  return (
    <GuardedShell>
      <AdminShell><TasksView /></AdminShell>
    </GuardedShell>
  );
}

function TasksView() {
  const [rows, setRows] = useState<ScheduledTask[] | null>(null);
  const [agents, setAgents] = useState<{ id: number; name: string }[]>([]);
  const [endpoints, setEndpoints] = useState<{ id: number; name: string }[]>([]);
  const [connectors, setConnectors] = useState<{ id: number; name: string }[]>([]);
  const [kbs, setKbs] = useState<{ id: number; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [runs, setRuns] = useState<{ id: number; rows: TaskRunInfo[] } | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, a, e, c, k] = await Promise.all([
        listTasks(), listAgents().catch(() => []), listA2AEndpoints().catch(() => []),
        listConnectors().catch(() => []), listKnowledgeBases().catch(() => []),
      ]);
      setRows(t);
      setAgents(a as { id: number; name: string }[]);
      setEndpoints(e as { id: number; name: string }[]);
      setConnectors(c as { id: number; name: string }[]);
      setKbs(k as { id: number; name: string }[]);
    } catch (e) { setError(e instanceof ApiError ? e.message : "加载失败"); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  function openCreate() { setEditing(null); setForm(EMPTY); setDialog(true); }
  function openEdit(t: ScheduledTask) {
    setEditing(t);
    setForm({
      name: t.name, enabled: t.enabled, schedule_kind: t.schedule_kind,
      every_seconds: String(t.every_seconds), cron_expr: t.cron_expr ?? "",
      action_type: t.action_type, target_agent_id: t.target_agent_id ?? "",
      a2a_endpoint_id: t.a2a_endpoint_id ?? "", payload: t.payload,
      delivery: t.delivery, webhook_url: t.webhook_url ?? "",
      connector_id: t.connector_id ?? "", knowledge_id: t.knowledge_id ?? "",
    });
    setDialog(true);
  }

  async function save() {
    setError(null); setOk(null);
    const body: Partial<ScheduledTask> = {
      name: form.name.trim(), enabled: form.enabled,
      schedule_kind: form.schedule_kind as "interval" | "cron",
      every_seconds: Number(form.every_seconds) || 3600, cron_expr: form.cron_expr || undefined,
      action_type: form.action_type as "agent_message" | "a2a_call",
      target_agent_id: form.action_type === "agent_message" ? Number(form.target_agent_id) : undefined,
      a2a_endpoint_id: form.action_type === "a2a_call" ? Number(form.a2a_endpoint_id) : undefined,
      payload: form.payload, delivery: form.delivery,
      webhook_url: form.webhook_url || undefined,
      connector_id: form.connector_id === "" ? undefined : Number(form.connector_id),
      knowledge_id: form.knowledge_id === "" ? undefined : Number(form.knowledge_id),
    };
    try {
      if (editing) await updateTask(editing.id, body);
      else await createTask(body);
      setDialog(false); setOk("已保存"); await load();
    } catch (e) { setError(e instanceof ApiError ? e.message : "保存失败"); }
  }

  async function run(t: ScheduledTask) {
    setError(null);
    try {
      // 立即执行改为异步：接口马上返回 run_id，不再阻塞到任务跑完。
      const r = await runTaskNow(t.id);
      setOk(`已提交执行（run #${r.run_id}），稍后可在「历史」中查看结果`);
      await load();
      // 后台轮询若干次，跑完再刷新一次历史与列表
      let tries = 0;
      const timer = window.setInterval(async () => {
        tries += 1;
        if (tries > 30) { window.clearInterval(timer); return; }
        try {
          const rows = await listTaskRuns(t.id);
          const hit = rows.find((x) => x.id === r.run_id);
          if (hit && hit.status !== "running") {
            window.clearInterval(timer);
            setOk(`执行完成（run #${r.run_id}）: ${hit.status}`);
            await load();
          }
        } catch { window.clearInterval(timer); }
      }, 2000);
    } catch (e) { setError(e instanceof ApiError ? e.message : "执行失败"); }
  }

  async function showRuns(t: ScheduledTask) {
    try { setRuns({ id: t.id, rows: await listTaskRuns(t.id) }); }
    catch (e) { setError(e instanceof ApiError ? e.message : "读取历史失败"); }
  }

  const num = (v: unknown, d: number) => (v === "" || v === null || v === undefined ? d : Number(v));

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>定时自动化任务</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>新建任务</Button>
      </Stack>
      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}
      {rows === null ? <SkeletonList rows={4} /> : rows.length === 0 ? (
        <EmptyState icon={<HistoryIcon />} title="还没有定时任务" hint="定时给 Agent 发消息或调用 A2A 端点，并可选择多种结果处理方式。" action={<Button onClick={openCreate}>新建任务</Button>} />
      ) : rows.map((t) => (
        <Card key={t.id}>
          <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{t.name}</Typography>
              <Chip size="small" label={t.enabled ? "启用" : "停用"} color={t.enabled ? "success" : "default"} />
              <Chip size="small" variant="outlined" label={t.action_type === "agent_message" ? "Agent 消息" : "A2A 调用"} />
              <Chip size="small" variant="outlined" label={t.schedule_kind === "interval" ? `每 ${t.every_seconds}s` : (t.cron_expr ?? "cron")} />
              <Chip size="small" label={t.delivery} />
              <Box sx={{ flexGrow: 1 }} />
              <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => run(t)}>立即运行</Button>
              <Button size="small" startIcon={<HistoryIcon />} onClick={() => showRuns(t)}>历史</Button>
              <Button size="small" onClick={() => openEdit(t)}>编辑</Button>
              <Button size="small" color="error" onClick={() => deleteTask(t.id).then(load)}>删除</Button>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {t.action_type === "agent_message" ? `Agent #${t.target_agent_id}` : `端点 #${t.a2a_endpoint_id}`} · 内容: {t.payload.slice(0, 80) || "(空)"}
            </Typography>
            {t.last_run_at ? <Typography variant="caption" color="text.secondary">上次执行: {t.last_run_at} · {t.last_status}</Typography> : null}
          </CardContent>
        </Card>
      ))}

      <Dialog open={dialog} onClose={() => setDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "编辑任务" : "新建任务"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label="任务名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <FormControlLabel control={<Checkbox checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />} label="启用" />
            <FormControl fullWidth>
              <InputLabel>调度方式</InputLabel>
              <Select value={form.schedule_kind} label="调度方式" onChange={(e) => setForm({ ...form, schedule_kind: e.target.value })}>
                <MenuItem value="interval">固定间隔</MenuItem><MenuItem value="cron">Cron 表达式</MenuItem>
              </Select>
            </FormControl>
            {form.schedule_kind === "interval" ? (
              <TextField label="间隔（秒）" type="number" value={form.every_seconds} onChange={(e) => setForm({ ...form, every_seconds: e.target.value })} />
            ) : (
              <TextField label="Cron（如 */30 * * * *）" value={form.cron_expr} onChange={(e) => setForm({ ...form, cron_expr: e.target.value })} />
            )}
            <FormControl fullWidth>
              <InputLabel>动作</InputLabel>
              <Select value={form.action_type} label="动作" onChange={(e) => setForm({ ...form, action_type: e.target.value })}>
                <MenuItem value="agent_message">给 Agent 发消息</MenuItem><MenuItem value="a2a_call">调用 A2A 端点</MenuItem>
              </Select>
            </FormControl>
            {form.action_type === "agent_message" ? (
              <FormControl fullWidth>
                <InputLabel>目标 Agent</InputLabel>
                <Select value={form.target_agent_id} label="目标 Agent" onChange={(e) => setForm({ ...form, target_agent_id: e.target.value as number })}>
                  {agents.map((a) => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
                </Select>
              </FormControl>
            ) : (
              <FormControl fullWidth>
                <InputLabel>A2A 端点</InputLabel>
                <Select value={form.a2a_endpoint_id} label="A2A 端点" onChange={(e) => setForm({ ...form, a2a_endpoint_id: e.target.value as number })}>
                  {endpoints.map((e) => <MenuItem key={e.id} value={e.id}>{e.name}</MenuItem>)}
                </Select>
              </FormControl>
            )}
            <TextField label="消息内容（Agent 动作）" multiline rows={3} value={form.payload} onChange={(e) => setForm({ ...form, payload: e.target.value })} />
            <FormControl fullWidth>
              <InputLabel>结果处理（逗号分隔，可多选）</InputLabel>
              <Select multiple value={form.delivery.split(",")} label="结果处理（逗号分隔，可多选）" onChange={(e) => setForm({ ...form, delivery: (e.target.value as string[]).join(",") })}>
                {Object.entries(DELIVERY_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
              </Select>
            </FormControl>
            {form.delivery.includes("webhook") ? <TextField label="Webhook URL" value={form.webhook_url} onChange={(e) => setForm({ ...form, webhook_url: e.target.value })} /> : null}
            {form.delivery.includes("connector") ? (
              <FormControl fullWidth><InputLabel>连接器</InputLabel>
                <Select value={form.connector_id} label="连接器" onChange={(e) => setForm({ ...form, connector_id: e.target.value as number })}>
                  {connectors.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
                </Select>
              </FormControl>
            ) : null}
            {form.delivery.includes("knowledge") ? (
              <FormControl fullWidth><InputLabel>目标知识库</InputLabel>
                <Select value={form.knowledge_id} label="目标知识库" onChange={(e) => setForm({ ...form, knowledge_id: e.target.value as number })}>
                  {kbs.map((k) => <MenuItem key={k.id} value={k.id}>{k.name}</MenuItem>)}
                </Select>
              </FormControl>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setDialog(false)}>取消</Button><Button variant="contained" onClick={save}>保存</Button></DialogActions>
      </Dialog>

      <Dialog open={runs !== null} onClose={() => setRuns(null)} maxWidth="sm" fullWidth>
        <DialogTitle>执行历史</DialogTitle>
        <DialogContent>
          {(runs?.rows ?? []).length === 0 ? <Typography color="text.secondary">暂无执行记录</Typography> :
            (runs?.rows ?? []).map((r) => (
              <Card key={r.id} sx={{ mb: 1 }}><CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Chip size="small" label={r.status} color={r.status === "ok" ? "success" : "error"} />
                  <Typography variant="caption">{r.started_at}</Typography>
                </Stack>
                <Typography variant="body2">{r.summary}</Typography>
                {r.delivered ? <Typography variant="caption" color="text.secondary">已处理: {r.delivered}</Typography> : null}
              </CardContent></Card>
            ))}
        </DialogContent>
        <DialogActions><Button onClick={() => setRuns(null)}>关闭</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}
