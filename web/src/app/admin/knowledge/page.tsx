"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Alert, Box, Button, Card, CardActions, CardContent, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton,
  MenuItem, Stack, Switch, TextField, Tooltip, Typography,
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
  createKnowledgeBase, createRagflowSite, deleteKnowledgeBase, deleteRagflowSite,
  getStoredUser, listKnowledgeBases, listRagflowSites, listSiteDatasets,
  testKnowledgeBase, testRagflowSite, updateKnowledgeBase, updateRagflowSite,
  type DatasetItem, type KnowledgeBase, type RagflowSite,
} from "@/lib/api";

type SiteForm = { name: string; base_url: string; api_key: string; is_shared: boolean; enabled: boolean };
type KbForm = { name: string; site_id: string; description: string; dataset_id: string; dataset_name: string; is_shared: boolean; enabled: boolean };
const EMPTY_SITE: SiteForm = { name: "", base_url: "", api_key: "", is_shared: false, enabled: true };
const EMPTY_KB: KbForm = { name: "", site_id: "", description: "", dataset_id: "", dataset_name: "", is_shared: false, enabled: true };

export default function KnowledgePage() {
  return <GuardedShell><AdminShell><KnowledgeInner /></AdminShell></GuardedShell>;
}

function KnowledgeInner() {
  const [sites, setSites] = useState<RagflowSite[] | null>(null);
  const [kbs, setKbs] = useState<KnowledgeBase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [siteOpen, setSiteOpen] = useState(false);
  const [siteEditId, setSiteEditId] = useState<number | null>(null);
  const [siteForm, setSiteForm] = useState<SiteForm>(EMPTY_SITE);
  const [kbOpen, setKbOpen] = useState(false);
  const [kbEditId, setKbEditId] = useState<number | null>(null);
  const [kbForm, setKbForm] = useState<KbForm>(EMPTY_KB);
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [loadingDs, setLoadingDs] = useState(false);
  const me = getStoredUser();

  const load = useCallback(async () => {
    try {
      const [s, k] = await Promise.all([listRagflowSites(), listKnowledgeBases()]);
      setSites(s); setKbs(k);
    } catch (e) { setError(e instanceof ApiError ? e.message : "加载失败"); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // ── 站点 ──
  function openSiteCreate() { setSiteEditId(null); setSiteForm(EMPTY_SITE); setSiteOpen(true); }
  function openSiteEdit(s: RagflowSite) {
    setSiteEditId(s.id);
    setSiteForm({ name: s.name, base_url: s.base_url, api_key: "", is_shared: s.is_shared, enabled: s.enabled });
    setSiteOpen(true);
  }
  async function saveSite() {
    setError(null); setOk(null);
    try {
      if (siteEditId === null) await createRagflowSite(siteForm);
      else {
        const body: Record<string, unknown> = { name: siteForm.name, base_url: siteForm.base_url, is_shared: siteForm.is_shared, enabled: siteForm.enabled };
        if (siteForm.api_key) body.api_key = siteForm.api_key;
        await updateRagflowSite(siteEditId, body);
      }
      setSiteOpen(false); setOk("站点已保存"); await load();
    } catch (e) { setError(e instanceof ApiError ? e.message : "保存失败"); }
  }
  async function fetchSiteDatasets(id: number) {
    setLoadingDs(true); setError(null);
    try { const d = await listSiteDatasets(id); setDatasets(d); if (!d.length) setOk("连接成功，但暂无知识库"); }
    catch (e) { setError(e instanceof ApiError ? e.message : "拉取数据集失败"); }
    finally { setLoadingDs(false); }
  }

  // ── 库 ──
  function openKbCreate() { setKbEditId(null); setKbForm(EMPTY_KB); setDatasets([]); setKbOpen(true); }
  function openKbEdit(k: KnowledgeBase) {
    setKbEditId(k.id);
    setKbForm({ name: k.name, site_id: String(k.site_id), description: k.description ?? "", dataset_id: k.dataset_id ?? "", dataset_name: k.dataset_name ?? "", is_shared: k.is_shared, enabled: k.enabled });
    setDatasets(k.dataset_id ? [{ id: k.dataset_id, name: k.dataset_name ?? k.dataset_id }] : []);
    setKbOpen(true);
  }
  async function onSiteChange(siteId: string) {
    setKbForm((f) => ({ ...f, site_id: siteId, dataset_id: "", dataset_name: "" }));
    setDatasets([]);
    if (siteId) await fetchSiteDatasets(Number(siteId));
  }
  async function saveKb() {
    setError(null); setOk(null);
    if (!kbForm.site_id || !kbForm.dataset_id) { setError("请选择站点和知识库"); return; }
    try {
      const body = {
        name: kbForm.name || kbForm.dataset_name, site_id: Number(kbForm.site_id),
        description: kbForm.description, dataset_id: kbForm.dataset_id,
        dataset_name: kbForm.dataset_name, is_shared: kbForm.is_shared, enabled: kbForm.enabled,
      };
      if (kbEditId === null) await createKnowledgeBase(body);
      else await updateKnowledgeBase(kbEditId, body);
      setKbOpen(false); setOk("知识库已保存"); await load();
    } catch (e) { setError(e instanceof ApiError ? e.message : "保存失败"); }
  }

  return (
    <Stack spacing={2}>
      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      <Card>
        <CardContent>
          <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
            <Typography variant="h6">RAGFlow 站点</Typography>
            <Button startIcon={<AddIcon />} onClick={openSiteCreate}>新建站点</Button>
          </Stack>
          <Typography variant="caption" color="text.secondary">站点连接信息只配置一次，下面可以挂多个知识库。</Typography>
        </CardContent>
      </Card>
      {sites === null ? <SkeletonList rows={2} /> : sites.length === 0 ? (
        <EmptyState icon={<StorageIcon />} title="还没有站点" hint="先配置一个 RAGFlow 站点的地址和 API Key" action={<Button onClick={openSiteCreate}>新建站点</Button>} />
      ) : (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 2 }}>
          {sites.map((s) => (
            <Card key={s.id}>
              <CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography sx={{ fontWeight: 600, flexGrow: 1 }}>{s.name}</Typography>
                  {s.has_api_key ? <Chip size="small" label="已配置Key" color="success" /> : <Chip size="small" label="无Key" />}
                  {!s.enabled ? <Chip size="small" label="停用" /> : null}
                </Stack>
                <Typography variant="caption" color="text.secondary">{s.base_url}</Typography>
              </CardContent>
              <CardActions>
                <Tooltip title="测试连接"><IconButton size="small" onClick={() => void testRagflowSite(s.id).then((r) => setOk(r.message)).catch((e) => setError(String(e)))}><TestIcon /></IconButton></Tooltip>
                <Tooltip title="查看数据集"><Button size="small" onClick={() => void fetchSiteDatasets(s.id)}>数据集</Button></Tooltip>
                <Tooltip title="编辑"><IconButton size="small" onClick={() => openSiteEdit(s)}><EditIcon /></IconButton></Tooltip>
                <Tooltip title="删除"><IconButton size="small" onClick={() => void deleteRagflowSite(s.id).then(() => load()).catch((e: ApiError) => { if (e.status === 409 && window.confirm("站点下有知识库，强制删除并解绑？")) void deleteRagflowSite(s.id, true).then(() => load()); else setError(String(e)); })}><DeleteIcon /></IconButton></Tooltip>
              </CardActions>
            </Card>
          ))}
        </Box>
      )}
      {datasets.length > 0 ? (
        <Card><CardContent>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>最近拉取的数据集（{datasets.length}）</Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
            {datasets.map((d) => <Chip key={d.id} label={`${d.name} (${d.id.slice(0, 8)})`} />)}
          </Stack>
        </CardContent></Card>
      ) : null}

      <Card>
        <CardContent>
          <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
            <Typography variant="h6">知识库（数据集）</Typography>
            <Button startIcon={<AddIcon />} onClick={openKbCreate}>新增知识库</Button>
          </Stack>
        </CardContent>
      </Card>
      {kbs === null ? <SkeletonList rows={2} /> : kbs.length === 0 ? (
        <EmptyState icon={<StorageIcon />} title="还没有知识库" hint="在站点下勾选一个数据集即可创建知识库" action={<Button onClick={openKbCreate}>新增知识库</Button>} />
      ) : (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 2 }}>
          {kbs.map((k) => (
            <Card key={k.id}>
              <CardContent>
                <Typography sx={{ fontWeight: 600 }}>{k.name}</Typography>
                <Typography variant="caption" color="text.secondary">{k.site_name} · {k.dataset_name || k.dataset_id}</Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  {k.is_shared ? <Chip size="small" label="共享" /> : null}
                  {!k.enabled ? <Chip size="small" label="停用" /> : null}
                </Stack>
              </CardContent>
              <CardActions>
                <Tooltip title="测试"><IconButton size="small" onClick={() => void testKnowledgeBase(k.id).then((r) => setOk(r.message)).catch((e) => setError(String(e)))}><TestIcon /></IconButton></Tooltip>
                <Tooltip title="编辑"><IconButton size="small" onClick={() => openKbEdit(k)}><EditIcon /></IconButton></Tooltip>
                <Tooltip title="删除"><IconButton size="small" onClick={() => void deleteKnowledgeBase(k.id).then(() => load()).catch((e: ApiError) => { if (e.status === 409 && window.confirm("有 Agent 绑定，强制删除并解绑？")) void deleteKnowledgeBase(k.id, true).then(() => load()); else setError(String(e)); })}><DeleteIcon /></IconButton></Tooltip>
              </CardActions>
            </Card>
          ))}
        </Box>
      )}

      <Dialog open={siteOpen} onClose={() => setSiteOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{siteEditId === null ? "新建站点" : "编辑站点"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField label="站点名称" value={siteForm.name} onChange={(e) => setSiteForm({ ...siteForm, name: e.target.value })} fullWidth />
            <TextField label="RAGFlow 地址" value={siteForm.base_url} onChange={(e) => setSiteForm({ ...siteForm, base_url: e.target.value })} fullWidth placeholder="http://host:port" />
            <TextField label="API Key" type="password" value={siteForm.api_key} onChange={(e) => setSiteForm({ ...siteForm, api_key: e.target.value })} fullWidth helperText={siteEditId !== null ? "留空表示不修改" : "必填"} />
            <FormControlLabel control={<Switch checked={siteForm.enabled} onChange={(e) => setSiteForm({ ...siteForm, enabled: e.target.checked })} />} label="启用" />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSiteOpen(false)}>取消</Button>
          <Button variant="contained" onClick={() => void saveSite()}>保存</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={kbOpen} onClose={() => setKbOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{kbEditId === null ? "新增知识库" : "编辑知识库"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField select label="站点" value={kbForm.site_id} onChange={(e) => void onSiteChange(e.target.value)} fullWidth>
              {(sites ?? []).filter((s) => s.enabled).map((s) => <MenuItem key={s.id} value={String(s.id)}>{s.name}</MenuItem>)}
            </TextField>
            {kbForm.site_id ? (
              <TextField select label="知识库（数据集）" value={kbForm.dataset_id} onChange={(e) => {
                const id = e.target.value;
                const d = datasets.find((x) => x.id === id);
                setKbForm({ ...kbForm, dataset_id: id, dataset_name: d?.name ?? id, name: kbForm.name || d?.name || "" });
              }} fullWidth disabled={loadingDs || datasets.length === 0}>
                {datasets.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
              </TextField>
            ) : <Alert severity="info">请先选择站点，系统会自动拉取该站点的数据集。</Alert>}
            <TextField label="显示名称" value={kbForm.name} onChange={(e) => setKbForm({ ...kbForm, name: e.target.value })} fullWidth />
            <TextField label="描述" value={kbForm.description} onChange={(e) => setKbForm({ ...kbForm, description: e.target.value })} fullWidth multiline rows={2} />
            <FormControlLabel control={<Switch checked={kbForm.enabled} onChange={(e) => setKbForm({ ...kbForm, enabled: e.target.checked })} />} label="启用" />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setKbOpen(false)}>取消</Button>
          <Button variant="contained" onClick={() => void saveKb()}>保存</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
