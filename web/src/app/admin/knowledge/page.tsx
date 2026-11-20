"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import StorageIcon from "@mui/icons-material/Storage";
import TestIcon from "@mui/icons-material/CheckCircle";
import { AdminShell } from "@/components/AdminShell";
import { EmptyState, SkeletonList } from "@/components/Common";
import { GuardedShell } from "@/lib/authGuard";
import {
  ApiError,
  createKnowledgeBase,
  deleteKnowledgeBase,
  getStoredUser,
  listKnowledgeBases,
  listRagflowDatasets,
  testKnowledgeBase,
  updateKnowledgeBase,
  type DatasetItem,
  type KnowledgeBase,
} from "@/lib/api";

type Form = {
  name: string;
  description: string;
  base_url: string;
  api_key: string;
  dataset_id: string;
  dataset_name: string;
  is_shared: boolean;
  enabled: boolean;
};
const EMPTY: Form = {
  name: "", description: "", base_url: "", api_key: "",
  dataset_id: "", dataset_name: "", is_shared: false, enabled: true,
};

export default function KnowledgePage() {
  return (
    <GuardedShell require="user">
      <AdminShell>
        <KnowledgeInner />
      </AdminShell>
    </GuardedShell>
  );
}

function KnowledgeInner() {
  const [rows, setRows] = useState<KnowledgeBase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [loadingDs, setLoadingDs] = useState(false);
  const me = getStoredUser();

  const load = useCallback(async () => {
    try { setRows(await listKnowledgeBases()); }
    catch (e) { setError(e instanceof ApiError ? e.message : "加载失败"); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  function openCreate() { setEditId(null); setForm(EMPTY); setDatasets([]); setOpen(true); }
  function openEdit(k: KnowledgeBase) {
    setEditId(k.id);
    setForm({
      name: k.name, description: k.description ?? "", base_url: k.base_url,
      api_key: "", dataset_id: k.dataset_id ?? "", dataset_name: k.dataset_name ?? "",
      is_shared: k.is_shared, enabled: k.enabled,
    });
    setDatasets(k.dataset_id ? [{ id: k.dataset_id, name: k.dataset_name ?? k.dataset_id }] : []);
    setOpen(true);
  }

  async function fetchDatasets() {
    if (!form.base_url || !form.api_key) {
      setError("请先填写 RAGFlow 地址和 API Key"); return;
    }
    setLoadingDs(true); setError(null);
    try {
      const r = await listRagflowDatasets({ base_url: form.base_url, api_key: form.api_key });
      setDatasets(r.datasets);
      if (r.datasets.length === 0) setOk("连接成功，但没有找到知识库");
    } catch (e) { setError(e instanceof ApiError ? e.message : "获取知识库失败"); }
    finally { setLoadingDs(false); }
  }

  async function save() {
    setError(null); setOk(null);
    try {
      const body: Record<string, unknown> = {
        name: form.name, description: form.description, base_url: form.base_url,
        dataset_id: form.dataset_id, dataset_name: form.dataset_name,
        is_shared: form.is_shared, enabled: form.enabled,
      };
      if (form.api_key) body.api_key = form.api_key;
      if (editId === null) {
        if (!form.api_key) { setError("新建时必须填写 API Key"); return; }
        await createKnowledgeBase(body as never);
      } else {
        await updateKnowledgeBase(editId, body);
      }
      setOpen(false); setOk("已保存"); await load();
    } catch (e) { setError(e instanceof ApiError ? e.message : "保存失败"); }
  }

  async function doTest(id: number) {
    setError(null); setOk(null);
    try {
      const r = await testKnowledgeBase(id);
      setOk(r.ok ? `连接正常：${r.message}` : `连接失败：${r.message}`);
    } catch (e) { setError(e instanceof ApiError ? e.message : "测试失败"); }
  }

  async function remove(k: KnowledgeBase) {
    setError(null);
    try {
      await deleteKnowledgeBase(k.id, false);
      setOk("已删除"); await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && confirm("该知识库已被 Agent 绑定，是否强制删除并解绑？")) {
        try { await deleteKnowledgeBase(k.id, true); setOk("已强制删除并解绑"); await load(); }
        catch (e2) { setError(e2 instanceof ApiError ? e2.message : "删除失败"); }
      } else setError(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>知识库</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>新建</Button>
      </Stack>
      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}
      {rows === null ? <SkeletonList rows={3} /> : rows.length === 0 ? (
        <EmptyState icon={<StorageIcon />} title="还没有知识库"
          hint="登记一个 RAGFlow 知识库，然后在 Agent 编辑页绑定，Agent 就具备了检索能力。"
          action={<Button variant="contained" onClick={openCreate}>新建知识库</Button>} />
      ) : (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          {rows.map((k) => (
            <Card key={k.id}>
              <CardContent>
                <Stack spacing={1}>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                    <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>{k.name}</Typography>
                    <Chip size="small" label={k.dataset_name ?? "未选数据集"} />
                    {k.is_shared ? <Chip size="small" color="info" label="共享" /> : null}
                    {!k.enabled ? <Chip size="small" label="已禁用" /> : null}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">{k.description || "暂无描述"}</Typography>
                  <Typography variant="caption" color="text.secondary">{k.base_url}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    API Key：{k.has_api_key ? "已配置（脱敏）" : "未配置"}
                  </Typography>
                </Stack>
              </CardContent>
              <CardActions>
                <Tooltip title="测试连接"><IconButton onClick={() => void doTest(k.id)}><TestIcon /></IconButton></Tooltip>
                {(me?.id === k.owner_id || me?.role === "admin") ? (
                  <>
                    <Tooltip title="编辑"><IconButton onClick={() => openEdit(k)}><EditIcon /></IconButton></Tooltip>
                    <Tooltip title="删除"><IconButton onClick={() => void remove(k)}><DeleteIcon /></IconButton></Tooltip>
                  </>
                ) : null}
              </CardActions>
            </Card>
          ))}
        </Box>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{editId === null ? "新建知识库" : "编辑知识库"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="名称" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <TextField label="描述" value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <TextField label="RAGFlow 地址" placeholder="http://ragflow.example.com" value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            <TextField label={editId === null ? "API Key" : "API Key（留空保持不变）"}
              type="password" value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
            <Button variant="outlined" onClick={() => void fetchDatasets()} disabled={loadingDs}>
              {loadingDs ? <CircularProgress size={18} /> : "拉取知识库列表"}
            </Button>
            {datasets.length > 0 ? (
              <TextField select label="知识库（Dataset）" value={form.dataset_id}
                onChange={(e) => {
                  const d = datasets.find((x) => x.id === e.target.value);
                  setForm({ ...form, dataset_id: e.target.value, dataset_name: d?.name ?? "" });
                }}>
                {datasets.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
              </TextField>
            ) : null}
            <FormControlLabel control={<Switch checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />} label="启用" />
            {(me?.role === "admin") ? (
              <FormControlLabel control={<Switch checked={form.is_shared}
                onChange={(e) => setForm({ ...form, is_shared: e.target.checked })} />} label="共享给其他用户" />
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button variant="contained" onClick={() => void save()}>保存</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
