"use client";

import { copyText } from "@/lib/clipboard";
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
  getEffectiveModel,
  getForcedToolsets,
  getAgentSoul,
  bindAgentSkills,
  createAgentAPIKey,
  createAndBindA2A,
  createAndBindMCP,
  deleteAgentAPIKey,
  getAgent,
  getAgentA2A,
  getAgentMCP,
  listA2AEndpoints,
  listAgentAPIKeys,
  listAgentCuratedSkills,
  listAgentBuiltinSkills,
  listAgentSkillBindings,
  listMCPServers,
  listModelTemplates,
  listSkills,
  listKnowledgeBases,
  type KnowledgeBase,
  getAgentKnowledge,
  setAgentKnowledge,
  setAgentA2A,
  setAgentBuiltinSkills,
  setAgentMCP,
  updateAgent,
  updateAgentAPIKey,
  type A2AEndpoint,
  type Agent,
  type AgentAPIKey,
  type AgentBuiltinSkill,
  type CustomSkill,
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
  const [forcedToolsets, setForcedToolsets] = useState<Record<string, string>>({});

  // 模型
  const [templates, setTemplates] = useState<ModelTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<number | "">("");
  const [effectiveModel, setEffectiveModel] = useState<Record<string, unknown> | null>(null);

  // MCP
  const [mcpAll, setMcpAll] = useState<MCPServer[]>([]);
  const [mcpBound, setMcpBound] = useState<number[]>([]);
  const [newMcpOpen, setNewMcpOpen] = useState(false);
  const [newMcp, setNewMcp] = useState({ name: "", url: "", token: "" });

  // Skill 绑定（内置与自定义完全独立的 state，避免高亮串台）
  const [skillsAll, setSkillsAll] = useState<CustomSkill[]>([]);
  const [skillBound, setSkillBound] = useState<number[]>([]);
  const [builtinSkills, setBuiltinSkills] = useState<AgentBuiltinSkill[]>([]);
  const [builtinSelected, setBuiltinSelected] = useState<string[]>([]);
  const [curated, setCurated] = useState<
    { name: string; description?: string | null; enabled: boolean; usage?: number }[]
  >([]);
  const [curatorOn, setCuratorOn] = useState(false);

  // A2A 绑定
  const [a2aAll, setA2aAll] = useState<A2AEndpoint[]>([]);
  const [a2aBound, setA2aBound] = useState<number[]>([]);
  const [newA2aOpen, setNewA2aOpen] = useState(false);
  const [newA2a, setNewA2a] = useState({ name: "", url: "", token: "" });

  // 知识库绑定
  const [knowledgeAll, setKnowledgeAll] = useState<KnowledgeBase[]>([]);
  const [knowledgeBound, setKnowledgeBound] = useState<number[]>([]);

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
      const [tpl, eff, mcp, bind, ks, skAll, skBind, a2aAllR, a2aBind, bs, kbAll, kbBind, forced, soulData] = await Promise.all([
        listModelTemplates().catch(() => []),
        getEffectiveModel(id).catch(() => ({ profile: "", model: {} })),
        listMCPServers().catch(() => []),
        getAgentMCP(id).catch(() => ({ bound: [] as MCPServer[] })),
        listAgentAPIKeys(id).catch(() => []),
        listSkills().catch(() => []),
        listAgentSkillBindings(id).catch(() => ({ bound: [] as CustomSkill[] })),
        listA2AEndpoints().catch(() => []),
        getAgentA2A(id).catch(() => ({ bound: [] as A2AEndpoint[] })),
        listAgentBuiltinSkills(id).catch(() => ({ skills: [] as AgentBuiltinSkill[] })),
        listKnowledgeBases().catch(() => []),
        getAgentKnowledge(id).catch(() => [] as KnowledgeBase[]),
        getForcedToolsets(id).catch(() => ({ forced: [], reasons: {} })),
        getAgentSoul(id).catch(() => ({ soul: "" })),
      ]);
      setTemplates(tpl);
      setEffectiveModel(eff.model ?? {});
      setMcpAll(mcp);
      setMcpBound((bind.bound ?? []).map((m) => m.id));
      setKeys(ks);
      setSkillsAll(skAll);
      setSkillBound((skBind.bound ?? []).map((s) => s.id));
      const a2aVisible = a2aAllR.filter((ep) => ep.target_agent_id !== id);
      setA2aAll(a2aVisible);
      const visibleIds = new Set(a2aVisible.map((ep) => ep.id));
      setA2aBound((a2aBind.bound ?? []).map((e) => e.id).filter((eid) => visibleIds.has(eid)));
      setBuiltinSkills(bs.skills ?? []);
      const cur = await listAgentCuratedSkills(id).catch(() => null);
      setCurated(cur?.skills ?? []);
      setCuratorOn(Boolean(cur?.curator_enabled));
      setBuiltinSelected((bs.skills ?? []).filter((s) => s.selected).map((s) => s.name));
      setKnowledgeAll(kbAll);
      setKnowledgeBound((kbBind ?? []).map((k: { id: number }) => k.id));
      setForcedToolsets(forced.reasons ?? {});
      setSoul(soulData.soul ?? "");
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
      const eff = await getEffectiveModel(id).catch(() => null);
      if (eff) setEffectiveModel(eff.model ?? {});
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

  async function saveBuiltin(names: string[]) {
    setBuiltinSelected(names); // 立即反馈，独立 state 不影响自定义
    try {
      const r = await setAgentBuiltinSkills(id, names);
      if (r.errors.length) setError(`部分内置 Skill 同步失败：${r.errors.join("; ")}`);
      else setOk("内置 Skill 选择已同步到 profile");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "内置 Skill 同步失败");
    }
  }

  async function saveSkills(ids: number[]) {
    try {
      await bindAgentSkills(id, ids);
      setSkillBound(ids);
      setOk("Skill 绑定已同步到 profile");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "绑定失败");
    }
  }

  async function saveA2a(ids: number[]) {
    try {
      await setAgentA2A(id, ids);
      setA2aBound(ids);
      setOk("A2A 端点绑定已同步到 profile");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "绑定失败");
    }
  }

  async function saveKnowledge(ids: number[]) {
    setBusy(true);
    try {
      const r = await setAgentKnowledge(id, ids);
      setKnowledgeBound(ids);
      setOk(`知识库绑定已同步（检索 Skill 已生成）`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "知识库绑定失败");
    } finally {
      setBusy(false);
    }
  }

  async function createAndBindA2a() {
    setBusy(true);
    try {
      const r = await createAndBindA2A(id, {
        name: newA2a.name.trim(),
        url: newA2a.url.trim(),
        auth_type: newA2a.token ? "bearer" : "none",
        token: newA2a.token || undefined,
      });
      setNewA2aOpen(false);
      setNewA2a({ name: "", url: "", token: "" });
      await load();
      setOk(r.created ? "已新建并绑定 A2A 端点" : "已绑定已存在的端点");
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
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
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
        <Tab label="Skill" />
        <Tab label="A2A" />
        <Tab label="知识库" />
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
            <ToolsetGrid disabledToolsets={disabledToolsets} onChange={setDisabledToolsets} forcedReasons={forcedToolsets} />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: "block" }}>
              保存后写入 profile 的 config.yaml。
            </Typography>
          </CardContent>
        </Card>
      )}

      {tab === 2 && (
        <>
        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>当前生效的模型（来自该 Agent 的 profile 配置）</Typography>
            {Object.keys(effectiveModel ?? {}).length === 0 ? (
              <Typography variant="body2" color="text.secondary">尚未应用模型。请在下方选择模板并应用。</Typography>
            ) : (
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                {Object.entries(effectiveModel ?? {}).map(([k, v]) => (
                  <Chip key={k} size="small" variant="outlined" label={`${k}: ${String(v)}`} />
                ))}
              </Stack>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
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
        </>
      )}

      {tab === 3 && (
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" sx={{ alignItems: "center" }}>
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
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
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
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" },
            gap: 2,
            alignItems: "start",
          }}
        >
          {/* 内置 Skill：独立 state（字符串名），默认全不选 */}
          <Card>
            <CardContent>
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                    内置 Skill
                  </Typography>
                  <Chip size="small" label={`已选 ${builtinSelected.length}/${builtinSkills.length}`} />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  hermes 自带技能，默认全不选；勾选后对该 Agent 启用。
                </Typography>
                {builtinSkills.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    hermes 未提供内置 Skill 列表（dashboard 不可用）。
                  </Typography>
                ) : (
                  builtinSkills.map((bs) => (
                    <FormControlLabel
                      key={bs.name}
                      control={
                        <Checkbox
                          checked={builtinSelected.includes(bs.name)}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...builtinSelected, bs.name]
                              : builtinSelected.filter((n) => n !== bs.name);
                            void saveBuiltin(next);
                          }}
                        />
                      }
                      label={
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          <ListItemText
                            primary={bs.name}
                            secondary={bs.description ?? ""}
                            sx={{ flexGrow: 1 }}
                          />
                        </Stack>
                      }
                    />
                  ))
                )}
              </Stack>
            </CardContent>
          </Card>

          {/* curator（技能策展器）自动生成的 Skill：归入自定义区，按实际启用状态显示 */}
          <Card>
            <CardContent>
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                    curator 生成的 Skill
                  </Typography>
                  <Chip
                    size="small"
                    color={curatorOn ? "success" : "default"}
                    label={curatorOn ? "curator 已开启" : "curator 已关闭"}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  Hermes 后台自动学习产生的技能（非平台下发）。curator 关闭后不再新增；
                  已有技能可在下方按实际启用状态查看。若与自定义 Skill 语义重叠，建议关闭以免模型选错。
                </Typography>
                {curated.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    暂无 curator 生成的技能。
                  </Typography>
                ) : (
                  curated.map((c) => (
                    <Stack
                      key={c.name}
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: "center" }}
                    >
                      <ListItemText
                        primary={c.name}
                        secondary={`${c.description ?? ""}${c.usage ? ` · 使用 ${c.usage} 次` : ""}`}
                        sx={{ flexGrow: 1 }}
                      />
                      <Chip
                        size="small"
                        variant={c.enabled ? "filled" : "outlined"}
                        color={c.enabled ? "success" : "default"}
                        label={c.enabled ? "已启用" : "已禁用"}
                      />
                    </Stack>
                  ))
                )}
              </Stack>
            </CardContent>
          </Card>

          {/* 自定义 Skill：独立 state（数字 ID） */}
          <Card>
            <CardContent>
              <Stack spacing={1}>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                    自定义 Skill
                  </Typography>
                  <Chip size="small" label={`已绑 ${skillBound.length}/${skillsAll.length}`} />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  平台内创建，写入该 Agent 的 profile（含 references/scripts/templates/assets）。
                </Typography>
                {skillsAll.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    还没有自定义 Skill。请到「自定义 Skill」页创建后再回来绑定。
                  </Typography>
                ) : (
                  skillsAll.map((sk) => (
                    <FormControlLabel
                      key={sk.id}
                      control={
                        <Checkbox
                          checked={skillBound.includes(sk.id)}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...skillBound, sk.id]
                              : skillBound.filter((x) => x !== sk.id);
                            void saveSkills(next);
                          }}
                        />
                      }
                      label={
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          <ListItemText primary={sk.name} secondary={sk.description ?? ""} />
                          {sk.is_shared ? <Chip size="small" label="共享" /> : null}
                        </Stack>
                      }
                    />
                  ))
                )}
              </Stack>
            </CardContent>
          </Card>
        </Box>
      )}

      {tab === 5 && (
        <Card>
          <CardContent>
            <Stack spacing={1.5}>
              <Stack direction="row" sx={{ alignItems: "center" }}>
                <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
                  已绑定的 A2A 出站端点
                </Typography>
                <Button startIcon={<AddIcon />} onClick={() => setNewA2aOpen(true)}>
                  新建并绑定
                </Button>
              </Stack>
              {a2aAll.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  还没有 A2A 出站端点，点「新建并绑定」创建第一个。
                </Typography>
              ) : (
                a2aAll.map((ep) => (
                  <FormControlLabel
                    key={ep.id}
                    control={
                      <Checkbox
                        checked={a2aBound.includes(ep.id)}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...a2aBound, ep.id]
                            : a2aBound.filter((x) => x !== ep.id);
                          void saveA2a(next);
                        }}
                      />
                    }
                    label={
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                        <ListItemText primary={ep.name} secondary={ep.url} />
                        {ep.is_shared ? <Chip size="small" label="共享" /> : null}
                      </Stack>
                    }
                  />
                ))
              )}
            </Stack>
          </CardContent>
        </Card>
      )}

      {tab === 6 && (
        <Card><CardContent><Stack spacing={2}>
          <Typography variant="subtitle1">绑定的知识库（RAGFlow）</Typography>
          <Typography variant="body2" color="text.secondary">
            勾选后自动为该 Agent 注入内置 RAGFlow 检索工具（MCP）。
            同一站点可勾选多个知识库，跨站点也支持；无需开启 terminal 工具集。
          </Typography>
          {knowledgeAll.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              还没有知识库。请先到「知识库」页配置站点并登记知识库。
            </Typography>
          ) : (() => {
            const bySite = new Map<string, typeof knowledgeAll>();
            knowledgeAll.forEach((kb) => {
              const key = kb.site_name || `站点 ${kb.site_id}`;
              if (!bySite.has(key)) bySite.set(key, []);
              bySite.get(key)!.push(kb);
            });
            return Array.from(bySite.entries()).map(([siteName, kbs]) => (
              <Box key={siteName}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{siteName}</Typography>
                <Stack spacing={0.5}>
                  {kbs.map((kb) => (
                    <FormControlLabel key={kb.id}
                      control={<Checkbox checked={knowledgeBound.includes(kb.id)} onChange={(e) => {
                        const next = e.target.checked
                          ? [...knowledgeBound, kb.id]
                          : knowledgeBound.filter((x) => x !== kb.id);
                        void saveKnowledge(next);
                      }} />}
                      label={<Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                        <ListItemText primary={kb.name} secondary={kb.dataset_name ?? kb.description ?? ""} />
                        {kb.is_shared ? <Chip size="small" label="共享" /> : null}
                      </Stack>} />
                  ))}
                </Stack>
              </Box>
            ));
          })()}
        </Stack></CardContent></Card>
      )}

      {tab === 7 && (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
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
                      onClick={() => void copyText(revealedKey)}
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
                <Stack key={k.id} direction="row" spacing={1} sx={{ alignItems: "center" }}>
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
                <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end" }}>
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

      {/* 新建并绑定 A2A 端点 */}
      {newA2aOpen ? (
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
          onClick={() => setNewA2aOpen(false)}
        >
          <Card sx={{ width: 460 }} onClick={(e) => e.stopPropagation()}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h6">新建并绑定 A2A 端点</Typography>
                <TextField
                  label="名称"
                  value={newA2a.name}
                  onChange={(e) => setNewA2a({ ...newA2a, name: e.target.value })}
                />
                <TextField
                  label="URL"
                  value={newA2a.url}
                  onChange={(e) => setNewA2a({ ...newA2a, url: e.target.value })}
                  placeholder="http://host:port"
                />
                <TextField
                  label="Bearer Token（可选）"
                  value={newA2a.token}
                  onChange={(e) => setNewA2a({ ...newA2a, token: e.target.value })}
                />
                <Stack direction="row" spacing={1} sx={{ justifyContent: "flex-end" }}>
                  <Button onClick={() => setNewA2aOpen(false)}>取消</Button>
                  <Button
                    variant="contained"
                    disabled={busy || !newA2a.name.trim() || !newA2a.url.trim()}
                    onClick={() => void createAndBindA2a()}
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
