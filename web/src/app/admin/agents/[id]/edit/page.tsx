"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  ApiError,
  applyModelTemplate,
  createAgentAPIKey,
  createAndBindMCP,
  deleteAgentAPIKey,
  getAgent,
  getAgentMCP,
  listAgentAPIKeys,
  listMCPServers,
  listModelTemplates,
  setAgentMCP,
  updateAgent,
  updateAgentAPIKey,
  type Agent,
  type AgentAPIKey,
  type MCPServer,
  type ModelTemplate,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, SkeletonList } from "@/components/Common";
import { ToolsetGrid } from "@/components/ToolsetGrid";

function EditInner() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useRouter();

  const [agent, setAgent] = useState<Agent | null>(null);
  const [tab, setTab] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 基本信息
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [soul, setSoul] = useState("");
  const [disabledToolsets, setDisabledToolsets] = useState<string[]>([]);

  // 模型
  const [templates, setTemplates] = useState<ModelTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<number | "">("");

  // MCP
  const [mcpAll, setMcpAll] = useState<MCPServer[]>([]);
  const [mcpBound, setMcpBound] = useState<number[]>([]);
  const [newMcpOpen, setNewMcpOpen] = useState(false);
  const [newMcp, setNewMcp] = useState({ name: "", url: "", token: "" });

  // API Key
  const [keys, setKeys] = useState<AgentAPIKey[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const a = await getAgent(id);
      setAgent(a);
      setName(a.name);
      setDescription(a.description ?? "");
      setDisabledToolsets(a.disabled_toolsets ?? []);
      const [tpl, mcp, bind, ks] = await Promise.all([
        listModelTemplates().catch(() => []),
        listMCPServers().catch(() => []),
        getAgentMCP(id).catch(() => ({ bound: [] as MCPServer[] })),
        listAgentAPIKeys(id).catch(() => []),
      ]);
      setTemplates(tpl);
      setMcpAll(mcp);
      setMcpBound((bind.bound ?? []).map((m) => m.id));
      setKeys(ks);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await updateAgent(id, {
        name: name.trim(),
        description: description.trim(),
        disabled_toolsets: disabledToolsets,
        ...(soul.trim() ? { soul: soul.trim() } : {}),
      });
      setOk("已保存");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function applyModel() {
    if (selectedTemplate === "") return;
    setBusy(true);
    try {
      await applyModelTemplate(id, Number(selectedTemplate));
      setOk("模型已应用");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "应用失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveMCP(ids: number[]) {
    try {
      await setAgentMCP(id, ids);
      setMcpBound(ids);
      setOk("MCP 绑定已同步到 profile");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "绑定失败");
    }
  }

  async function createAndBindMcp() {
    setBusy(true);
    try {
      const r = await createAndBindMCP(id, {
        name: newMcp.name.trim(),
        transport: "http",
        url: newMcp.url.trim(),
        auth_type: newMcp.token ? "bearer" : "none",
        token: newMcp.token || undefined,
      });
      setNewMcpOpen(false);
      setNewMcp({ name: "", url: "", token: "" });
      await load();
      setOk(r.created ? "已新建并绑定" : "已绑定已存在的服务器");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "新建并绑定失败");
    } finally {
      setBusy(false);
    }
  }

  async function addKey() {
    if (!newKeyName.trim()) return;
    try {
      const k = await createAgentAPIKey(id, newKeyName.trim());
      setRevealedKey(k.key);
      setNewKeyName("");
      setKeys(await listAgentAPIKeys(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "生成失败");
    }
  }

  if (!agent) {
    return (
      <AdminShell>
        <SkeletonList rows={4} />
      </AdminShell>
    );
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          {agent.name}
        </Typography>
        <Chip size="small" label={agent.status === "published" ? "已发布" : "草稿"} />
        <Button onClick={() => router.push("/admin")}>返回列表</Button>
        <Button variant="contained" disabled={busy} onClick={() => void save()}>
          保存
        </Button>
      </Stack>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      <Tabs value={tab} onChange={(_, v) => setTab(v)}>
        <Tab label="基本" />
        <Tab label="工具" />
        <Tab label="模型" />
        <Tab label="MCP" />
        <Tab label="API 密钥" />
      </Tabs>

      {tab === 0 && (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <TextField label="名称" value={name} onChange={(e) => setName(e.target.value)} />
              <TextField
                label="描述"
                multiline
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <TextField
                label="人格（SOUL）"
                multiline
                rows={4}
                value={soul}
                onChange={(e) => setSoul(e.target.value)}
                helperText="留空则不修改"
              />
              <Typography variant="caption" color="text.disabled" sx={{ fontFamily: "monospace" }}>
                profile: {agent.profile_name} · owner: {agent.owner_id}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      {tab === 1 && (
        <Card>
          <CardContent>
            <ToolsetGrid disabledToolsets={disabledToolsets} onChange={setDisabledToolsets} />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: "block" }}>
              保存后写入 profile 的 config.yaml。
            </Typography>
          </CardContent>
        </Card>
      )}

      {tab === 2 && (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center">
                <TextField
                  select
                  label="选择模型模板"
                  value={selectedTemplate}
                  onChange={(e) =>
                    setSelectedTemplate(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  sx={{ maxWidth: 360 }}
                >
                  {templates.map((t) => (
                    <MenuItem key={t.id} value={t.id}>
                      {t.name}（{t.model}）
                    </MenuItem>
                  ))}
                </TextField>
                <Button disabled={busy || selectedTemplate === ""} onClick={() => void applyModel()}>
                  应用
                </Button>
                <Button startIcon={<AddIcon />} onClick={() => router.push("/admin/models")}>
                  新建模板
                </Button>
              </Stack>
              <Typography variant="caption" color="text.secondary">
                模板写入该 Agent 的 config.yaml: model 段。
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      {tab === 3 && (
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" alignItems="center">
                <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                  已绑定 MCP 服务器
                </Typography>
                <Button startIcon={<AddIcon />} onClick={() => setNewMcpOpen(true)}>
                  新建并绑定
                </Button>
              </Stack>
              {mcpAll.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  还没有 MCP 服务器，点「新建并绑定」创建第一个。
                </Typography>
              ) : (
                mcpAll.map((m) => (
                  <FormControlLabel
                    key={m.id}
                    control={
                      <Checkbox
                        checked={mcpBound.includes(m.id)}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...mcpBound, m.id]
                            : mcpBound.filter((x) => x !== m.id);
                          void saveMCP(next);
                        }}
                      />
                    }
                    label={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <ListItemText primary={m.name} secondary={m.transport} />
                        {m.is_shared ? <Chip size="small" label="共享" /> : null}
                      </Stack>
                    }
                  />
                ))
              )}
            </Stack>
          </CardContent>
        </Card>
      )}

      {tab === 4 && (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center">
                <TextField
                  label="新 Key 名称"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  sx={{ maxWidth: 280 }}
                />
                <Button variant="contained" onClick={() => void addKey()}>
                  生成
                </Button>
              </Stack>

              {revealedKey ? (
                <Alert
                  severity="warning"
                  action={
                    <IconButton
                      size="small"
                      onClick={() => void navigator.clipboard.writeText(revealedKey)}
                    >
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  }
                >
                  明文仅显示一次，请立即保存：
                  <Box component="code" sx={{ display: "block", mt: 1, wordBreak: "break-all" }}>
                    {revealedKey}
                  </Box>
                </Alert>
              ) : null}

              <Divider />
              {keys.map((k) => (
                <Stack key={k.id} direction="row" spacing={1} alignItems="center">
                  <Typography sx={{ width: 140 }}>{k.name}</Typography>
                  <Typography variant="caption" sx={{ fontFamily: "monospace", flexGrow: 1 }}>
                    {k.key_prefix}…
                  </Typography>
                  <Chip
                    size="small"
                    label={k.enabled ? "启用" : "禁用"}
                    color={k.enabled ? "success" : "default"}
                    variant="outlined"
                  />
                  <Button
                    size="small"
                    onClick={async () => {
                      await updateAgentAPIKey(id, k.id, { enabled: !k.enabled });
                      setKeys(await listAgentAPIKeys(id));
                    }}
                  >
                    {k.enabled ? "禁用" : "启用"}
                  </Button>
                  <IconButton
                    size="small"
                    color="error"
                    onClick={async () => {
                      await deleteAgentAPIKey(id, k.id);
                      setKeys(await listAgentAPIKeys(id));
                    }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
              {keys.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  还没有 API Key。生成后可通过 /api/v1/agents/{agent.slug}/messages 调用。
                </Typography>
              ) : null}
            </Stack>
          </CardContent>
        </Card>
      )}

      {/* 新建并绑定 MCP */}
      {newMcpOpen ? (
        <Box
          sx={{
            position: "fixed",
            inset: 0,
            bgcolor: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1300,
          }}
          onClick={() => setNewMcpOpen(false)}
        >
          <Card sx={{ width: 460 }} onClick={(e) => e.stopPropagation()}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">新建并绑定 MCP 服务器</Typography>
                <TextField
                  label="名称"
                  value={newMcp.name}
                  onChange={(e) => setNewMcp({ ...newMcp, name: e.target.value })}
                />
                <TextField
                  label="URL"
                  value={newMcp.url}
                  onChange={(e) => setNewMcp({ ...newMcp, url: e.target.value })}
                  placeholder="https://mcp.example.com/v1"
                />
                <TextField
                  label="Bearer Token（可选）"
                  value={newMcp.token}
                  onChange={(e) => setNewMcp({ ...newMcp, token: e.target.value })}
                />
                <Stack direction="row" spacing={1} justifyContent="flex-end">
                  <Button onClick={() => setNewMcpOpen(false)}>取消</Button>
                  <Button
                    variant="contained"
                    disabled={busy || !newMcp.name.trim() || !newMcp.url.trim()}
                    onClick={() => void createAndBindMcp()}
                  >
                    创建并绑定
                  </Button>
                </Stack>
              </Stack>
            </CardContent>
          </Card>
        </Box>
      ) : null}
    </Stack>
  );
}

export default function AgentEditPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <EditInner />
      </AdminShell>
    </GuardedShell>
  );
}
