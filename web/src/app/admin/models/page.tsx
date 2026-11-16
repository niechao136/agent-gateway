"use client";

import { useCallback, useEffect, useState } from "react";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Box from "@mui/material/Box";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import TextField from "@mui/material/TextField";
import Stack from "@mui/material/Stack";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  ApiError,
  createModelTemplate,
  deleteModelTemplate,
  listModelTemplates,
  type ModelTemplate,
} from "@/lib/api";
import { GuardedShell } from "@/lib/authGuard";
import { AdminNav } from "@/components/AdminNav";

export default function AdminModelsPage() {
  return (
    <GuardedShell require="admin">
      <ModelsView />
    </GuardedShell>
  );
}

function ModelsView() {
  const [items, setItems] = useState<ModelTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(await listModelTemplates());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function remove(id: number) {
    if (!confirm("删除该模型模板？已应用到 Agent 的配置不受影响。")) return;
    try {
      await deleteModelTemplate(id);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "删除失败");
    }
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
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            管理中心
          </Typography>
          <AdminNav current="models" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
          <Typography variant="h5" sx={{ fontWeight: 700, flexGrow: 1 }}>
            模型模板
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
            新建模板
          </Button>
        </Box>

        <Alert severity="info" sx={{ mb: 2 }}>
          模板是「可复用的模型配置」。在 Agent 编辑页可一键应用到该 Agent。
        </Alert>

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}

        {items === null ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : items.length === 0 ? (
          <Alert severity="info">还没有模型模板。点右上角新建。</Alert>
        ) : (
          <Paper>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>名称</TableCell>
                  <TableCell>模型</TableCell>
                  <TableCell>provider</TableCell>
                  <TableCell>base_url</TableCell>
                  <TableCell align="center">API Key</TableCell>
                  <TableCell align="center">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((t) => (
                  <TableRow key={t.id} hover>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {t.name}
                      </Typography>
                      {t.description ? (
                        <Typography variant="caption" color="text.secondary">
                          {t.description}
                        </Typography>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <code style={{ fontSize: 12 }}>{t.model}</code>
                    </TableCell>
                    <TableCell>
                      <Chip size="small" label={t.provider} variant="outlined" />
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption">{t.base_url || "—"}</Typography>
                    </TableCell>
                    <TableCell align="center">
                      <Chip
                        size="small"
                        label={t.has_api_key ? "已配置" : "无"}
                        color={t.has_api_key ? "success" : "default"}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell align="center">
                      <IconButton size="small" aria-label="删除" onClick={() => void remove(t.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        )}
      </Container>

      <CreateModelDialog
        open={open}
        onClose={() => setOpen(false)}
        onCreated={async () => {
          setOpen(false);
          await reload();
        }}
        onError={setError}
      />
    </Box>
  );
}

function CreateModelDialog({
  open,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  onError: (m: string) => void;
}) {
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("custom");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  function reset() {
    setName("");
    setModel("");
    setBaseUrl("");
    setApiKey("");
    setDescription("");
    setProvider("custom");
  }

  async function submit() {
    setBusy(true);
    try {
      await createModelTemplate({
        name: name.trim(),
        model: model.trim(),
        provider: provider.trim() || "custom",
        ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      });
      reset();
      await onCreated();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>新建模型模板</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="模板名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
            placeholder="gemini-fast"
          />
          <TextField
            label="模型 ID"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            required
            placeholder="gemini-2.5-flash"
          />
          <TextField
            label="provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            helperText="自定义 OpenAI 兼容端点用 custom"
          />
          <TextField
            label="base_url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="http://127.0.0.1:8899/v1beta/openai"
            helperText="留空则用 provider 的默认地址"
          />
          <TextField
            label="API Key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type="password"
            helperText="会写入 profile 的 config.yaml（model.api_key）"
          />
          <TextField
            label="描述"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          取消
        </Button>
        <Button
          variant="contained"
          onClick={() => void submit()}
          disabled={busy || !name.trim() || !model.trim()}
        >
          {busy ? "创建中…" : "创建"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
