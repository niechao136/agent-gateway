"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Chip from "@mui/material/Chip";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import IconButton from "@mui/material/IconButton";
import { ApiError, getAgent, updateAgent, type Agent } from "@/lib/api";
import { GuardedShell } from "@/lib/authGuard";
import { AdminNav } from "@/components/AdminNav";
import { SkillsPanel } from "@/components/SkillsPanel";
import { A2APanel } from "@/components/A2APanel";
import { MCPPanel } from "@/components/MCPPanel";
import { ModelPanel } from "@/components/ModelPanel";

export default function EditAgentPage() {
  return (
    <GuardedShell require="admin">
      <EditAgent />
    </GuardedShell>
  );
}

function EditAgent() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [agent, setAgent] = useState<Agent | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [soul, setSoul] = useState("");
  const [model, setModel] = useState("");
  const [tier, setTier] = useState("public");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAgent(id)
      .then((a) => {
        setAgent(a);
        setName(a.name);
        setDescription(a.description ?? "");
        setTier(a.toolset_tier);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载失败"));
  }, [id]);

  async function save() {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await updateAgent(id, {
        name: name.trim(),
        description: description.trim(),
        toolset_tier: tier,
        ...(soul.trim() ? { soul: soul.trim() } : {}),
        ...(model.trim() ? { model: model.trim() } : {}),
      });
      setOk("已保存。新的对话会使用新配置，已存在的会话保持不变。");
      setSoul("");
      setModel("");
      const fresh = await getAgent(id);
      setAgent(fresh);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  if (!agent && !error) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 12 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <AppBar
        position="sticky"
        color="inherit"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: "divider" }}
      >
        <Toolbar>
          <IconButton edge="start" onClick={() => router.push("/admin")} aria-label="返回">
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            编辑 Agent
          </Typography>
          <AdminNav current="agents" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}
        {ok ? (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setOk(null)}>
            {ok}
          </Alert>
        ) : null}

        <Paper sx={{ p: 3 }}>
          <Stack spacing={2.5}>
            <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
              <Chip size="small" label={`slug: ${agent?.slug}`} variant="outlined" />
              <Chip
                size="small"
                label={`profile: ${agent?.profile_name}`}
                variant="outlined"
              />
              <Chip
                size="small"
                label={agent?.status === "published" ? "已发布" : "草稿"}
                color={agent?.status === "published" ? "success" : "default"}
              />
              {agent?.gateway_running ? (
                <Chip size="small" label="gateway 运行中" color="success" variant="outlined" />
              ) : null}
            </Box>

            <TextField label="名称" value={name} onChange={(e) => setName(e.target.value)} />
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
              minRows={5}
              placeholder="留空表示不修改"
              helperText="修改后会写入 hermes profile 的 SOUL.md。留空则保持原样。"
            />
            <TextField
              label="模型"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="留空表示不修改"
              helperText="例如 gemini-2.5-flash。留空则保持原样。"
            />
            <TextField
              select
              label="工具档位"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              helperText={`当前禁用：${
                agent?.disabled_toolsets.length ? agent.disabled_toolsets.join(", ") : "无"
              }`}
            >
              <MenuItem value="public">public — 无 terminal/file/browser</MenuItem>
              <MenuItem value="member">member — 额外放开 memory</MenuItem>
              <MenuItem value="admin">admin — 全部放开（仅管理员自用）</MenuItem>
            </TextField>

            <Box sx={{ display: "flex", gap: 1 }}>
              <Button variant="contained" onClick={() => void save()} disabled={busy}>
                {busy ? "保存中…" : "保存"}
              </Button>
              <Button onClick={() => router.push("/admin")}>返回列表</Button>
            </Box>

            <Alert severity="info">
              修改配置后，<strong>新会话</strong>生效；已存在的会话保持原配置。
            </Alert>
          </Stack>
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            Skills
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            启用后该 Agent 的会话即可使用这些技能。hermes 的 skill 是 profile 级开关。
          </Typography>
          <SkillsPanel agentId={id} />
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            A2A 端点
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            配置该 Agent 可以调用的外部 Agent。保存后写入 profile 的 config.yaml。
          </Typography>
          <A2APanel agentId={id} />
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            MCP 服务器
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            这些服务器提供的工具会挂到该 Agent 上。保存后写入 profile 的 config.yaml。
          </Typography>
          <MCPPanel agentId={id} />
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            模型
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            应用模型模板会写入该 Agent 的 profile 配置（其他配置保留）。
          </Typography>
          <ModelPanel agentId={id} />
        </Paper>
      </Container>
    </Box>
  );
}
