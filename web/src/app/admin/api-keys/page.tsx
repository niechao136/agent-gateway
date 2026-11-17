"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import {
  ApiError,
  createAgentAPIKey,
  listAgentAPIKeys,
  listAgents,
  type Agent,
  type AgentAPIKey,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { EmptyState, SkeletonList } from "@/components/Common";

interface AgentWithKeys {
  agent: Agent;
  keys: AgentAPIKey[];
}

function ApiKeysInner() {
  const [groups, setGroups] = useState<AgentWithKeys[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 生成弹窗
  const [genFor, setGenFor] = useState<Agent | null>(null);
  const [keyName, setKeyName] = useState("default");
  const [revealed, setRevealed] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const agents = await listAgents();
      const withKeys = await Promise.all(
        agents.map(async (agent) => ({
          agent,
          keys: await listAgentAPIKeys(agent.id).catch(() => []),
        })),
      );
      setGroups(withKeys);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function generate() {
    if (!genFor) return;
    try {
      const k = await createAgentAPIKey(genFor.id, keyName.trim() || "default");
      setRevealed(k.key);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "生成失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5">API 密钥</Typography>
      <Typography variant="body2" color="text.secondary">
        每个 Agent 的对外 API 凭证（agk_ 前缀），用于 /api/v1/agents/&#123;slug&#125;/messages。明文仅生成时显示一次。
      </Typography>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}

      {groups === null ? (
        <SkeletonList />
      ) : groups.length === 0 ? (
        <EmptyState icon={<Box>🔑</Box>} title="还没有 Agent" hint="先在 Agent 页创建。" />
      ) : (
        groups.map(({ agent, keys }) => (
          <Card key={agent.id}>
            <CardContent>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                <Typography fontWeight={700}>{agent.name}</Typography>
                <Typography variant="caption" sx={{ fontFamily: "monospace" }}>
                  {agent.slug}
                </Typography>
                <Button
                  size="small"
                  startIcon={<AddIcon />}
                  sx={{ ml: "auto" }}
                  onClick={() => {
                    setGenFor(agent);
                    setKeyName("default");
                    setRevealed(null);
                  }}
                >
                  生成 Key
                </Button>
              </Stack>
              {keys.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  暂无密钥
                </Typography>
              ) : (
                keys.map((k) => (
                  <Stack key={k.id} direction="row" spacing={1} alignItems="center" sx={{ py: 0.5 }}>
                    <Typography sx={{ width: 120 }}>{k.name}</Typography>
                    <Typography variant="caption" sx={{ fontFamily: "monospace", flexGrow: 1 }}>
                      {k.key_prefix}…
                    </Typography>
                    <Chip
                      size="small"
                      label={k.enabled ? "启用" : "禁用"}
                      color={k.enabled ? "success" : "default"}
                      variant="outlined"
                    />
                    {k.last_used_at ? (
                      <Typography variant="caption" color="text.disabled">
                        最近使用 {new Date(k.last_used_at).toLocaleString()}
                      </Typography>
                    ) : null}
                  </Stack>
                ))
              )}
            </CardContent>
          </Card>
        ))
      )}

      {/* 生成弹窗（明文只显示一次） */}
      <Dialog
        open={genFor !== null}
        onClose={() => {
          setGenFor(null);
          setRevealed(null);
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>生成 API Key{genFor ? `：${genFor.name}` : ""}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {revealed ? (
              <Alert
                severity="warning"
                action={
                  <IconButton
                    size="small"
                    onClick={() => void navigator.clipboard.writeText(revealed)}
                  >
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                }
              >
                明文仅显示一次，请立即保存：
                <Box component="code" sx={{ display: "block", mt: 1, wordBreak: "break-all" }}>
                  {revealed}
                </Box>
              </Alert>
            ) : (
              <TextField
                label="Key 名称"
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                autoFocus
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          {revealed ? (
            <Button
              onClick={() => {
                setGenFor(null);
                setRevealed(null);
              }}
            >
              完成
            </Button>
          ) : (
            <>
              <Button onClick={() => setGenFor(null)}>取消</Button>
              <Button variant="contained" onClick={() => void generate()}>
                生成
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export default function ApiKeysPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <ApiKeysInner />
      </AdminShell>
    </GuardedShell>
  );
}
