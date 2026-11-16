"use client";

import { useCallback, useEffect, useState } from "react";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Paper from "@mui/material/Paper";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import RefreshIcon from "@mui/icons-material/Refresh";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import { GuardedShell } from "@/lib/authGuard";
import { AdminNav } from "@/components/AdminNav";

interface InboundStatus {
  host: string;
  port: number;
  probe_base: string;
  bearer_token_masked: string | null;
  peer_tokens_count: number;
  trusted_peers: string | null;
  allow_all_users: boolean;
  checks: Record<string, boolean>;
  ready: boolean;
  reachable: boolean;
  agent_card: {
    name?: string;
    description?: string;
    url?: string;
    version?: string;
    skills?: { id?: string; name?: string; description?: string }[];
    capabilities?: Record<string, unknown>;
  } | null;
  error: string | null;
}

export default function A2AInboundPage() {
  return (
    <GuardedShell require="admin">
      <InboundView />
    </GuardedShell>
  );
}

function InboundView() {
  const [data, setData] = useState<InboundStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const token = localStorage.getItem("ag_token");
      const r = await fetch("/api/admin/a2a-inbound", {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <AppBar
        position="sticky"
        color="inherit"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: "divider" }}
      >
        <Toolbar>
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            管理中心
          </Typography>
          <AdminNav current="a2a" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
          <Typography variant="h5" sx={{ fontWeight: 700, flexGrow: 1 }}>
            A2A 入站
          </Typography>
          <Button startIcon={<RefreshIcon />} onClick={() => void load()} disabled={busy}>
            刷新
          </Button>
        </Box>

        <Alert severity="info" sx={{ mb: 2 }}>
          入站表示「外部 Agent 可以调用本平台」。配置来自 hermes 的 .env，
          需重启 hermes 生效。三项缺一不可：token、host 放开、trusted peers。
        </Alert>

        {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

        {data === null ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : (
          <Stack spacing={2}>
            <Paper sx={{ p: 2.5 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                状态
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap" }}>
                <Chip
                  icon={data.ready ? <CheckCircleIcon /> : <CancelIcon />}
                  label={data.ready ? "配置完整" : "配置不完整"}
                  color={data.ready ? "success" : "error"}
                />
                <Chip
                  icon={data.reachable ? <CheckCircleIcon /> : <CancelIcon />}
                  label={data.reachable ? "服务可达" : "服务不可达"}
                  color={data.reachable ? "success" : "warning"}
                  variant="outlined"
                />
              </Stack>

              <Divider sx={{ my: 1.5 }} />

              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                配置检查
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>检查项</TableCell>
                    <TableCell>结果</TableCell>
                    <TableCell>说明</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  <CheckRow
                    name="token_configured"
                    ok={data.checks.token_configured}
                    desc="A2A_BEARER_TOKEN 或 A2A_PEER_TOKENS（缺失则只绑 127.0.0.1）"
                  />
                  <CheckRow
                    name="host_widened"
                    ok={data.checks.host_widened}
                    desc="A2A_HOST=0.0.0.0（缺失则出不了容器）"
                  />
                  <CheckRow
                    name="trusted_peers_configured"
                    ok={data.checks.trusted_peers_configured}
                    desc="A2A_TRUSTED_PEERS（缺失则 dispatch 被拒：peer not trusted）"
                  />
                </TableBody>
              </Table>

              <Divider sx={{ my: 1.5 }} />

              <Stack spacing={0.5}>
                <Row k="监听地址" v={`${data.host}:${data.port}`} />
                <Row k="探测地址" v={data.probe_base} />
                <Row k="Bearer Token" v={data.bearer_token_masked ?? "未配置"} />
                <Row k="Peer Tokens" v={`${data.peer_tokens_count} 个`} />
                <Row k="Trusted Peers" v={data.trusted_peers ?? "未配置"} />
                <Row k="Allow All Users" v={data.allow_all_users ? "是（仅开发）" : "否"} />
              </Stack>

              {data.error ? (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  {data.error}
                </Alert>
              ) : null}
            </Paper>

            {data.agent_card ? (
              <Paper sx={{ p: 2.5 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
                  Agent Card
                </Typography>
                <Stack spacing={0.5} sx={{ mb: 2 }}>
                  <Row k="名称" v={data.agent_card.name ?? "—"} />
                  <Row k="版本" v={data.agent_card.version ?? "—"} />
                  <Row k="URL" v={data.agent_card.url ?? "—"} />
                  <Row k="技能数" v={String(data.agent_card.skills?.length ?? 0)} />
                </Stack>
                {data.agent_card.skills?.length ? (
                  <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                    {data.agent_card.skills.slice(0, 40).map((s, i) => (
                      <Chip
                        key={s.id ?? i}
                        size="small"
                        variant="outlined"
                        label={s.name ?? s.id ?? `skill-${i}`}
                      />
                    ))}
                  </Box>
                ) : null}
              </Paper>
            ) : null}
          </Stack>
        )}
      </Container>
    </Box>
  );
}

function CheckRow({ name, ok, desc }: { name: string; ok: boolean; desc: string }) {
  return (
    <TableRow>
      <TableCell>
        <code style={{ fontSize: 12 }}>{name}</code>
      </TableCell>
      <TableCell>
        <Chip
          size="small"
          label={ok ? "通过" : "缺失"}
          color={ok ? "success" : "error"}
          variant="outlined"
        />
      </TableCell>
      <TableCell>
        <Typography variant="caption" color="text.secondary">
          {desc}
        </Typography>
      </TableCell>
    </TableRow>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <Box sx={{ display: "flex", gap: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 110 }}>
        {k}
      </Typography>
      <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
        {v}
      </Typography>
    </Box>
  );
}
