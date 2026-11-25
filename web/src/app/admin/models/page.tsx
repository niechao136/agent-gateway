"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import {
  ApiError,
  createModelTemplate,
  deleteModelTemplate,
  getRole,
  listModelTemplates,
  testModelTemplate,
  updateModelTemplate,
  type ModelTemplate,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, EmptyState, SkeletonList } from "@/components/Common";

interface Form {
  name: string;
  model: string;
  provider: string;
  base_url: string;
  context_length: number;
  api_key: string;
  description: string;
  is_shared: boolean;
}

// hermes 常见 provider；custom 用于 OpenAI 兼容端点（见 models_cfg.py 实测）
const PROVIDERS = [
  "anthropic",
  "openai",
  "gemini",
  "openrouter",
  "deepseek",
  "ollama",
  "custom",
];

const EMPTY: Form = {
  name: "",
  model: "",
  provider: "custom",
  base_url: "",
  context_length: 64000,
  api_key: "",
  description: "",
  is_shared: false,
};

function ModelsInner() {
  const [rows, setRows] = useState<ModelTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ModelTemplate | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const isAdmin = getRole() === "admin";

  const load = useCallback(async () => {
    try {
      setRows(await listModelTemplates());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit() {
    try {
      if (editing) {
        await updateModelTemplate(editing.id, {
          model: form.model.trim() || undefined,
          provider: form.provider.trim() || undefined,
          base_url: form.base_url.trim() || undefined,
          context_length: form.context_length,
          api_key: form.api_key || undefined, // 留空 = 不更新
          description: form.description.trim() || undefined,
          ...(isAdmin ? { is_shared: form.is_shared } : {}),
        });
      } else {
        await createModelTemplate({
          name: form.name.trim(),
          model: form.model.trim(),
          provider: form.provider.trim() || undefined,
          base_url: form.base_url.trim() || undefined,
          context_length: form.context_length,
          api_key: form.api_key || undefined,
          description: form.description.trim() || undefined,
          is_shared: form.is_shared,
        });
      }
      setOpen(false);
      setOk("已保存");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          模型模板
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => {
            setEditing(null);
            setForm(EMPTY);
            setOpen(true);
          }}
        >
          新建模板
        </Button>
      </Stack>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {rows === null ? (
        <SkeletonList />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<AddIcon fontSize="inherit" />}
          title="还没有模型模板"
          hint="模板保存 provider / model / base_url / api_key，在 Agent 编辑页一键应用。"
        />
      ) : (
        <Stack spacing={1}>
          {rows.map((t) => (
            <Card key={t.id}>
              <CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography sx={{ fontWeight: 700 }}>{t.name}</Typography>
                  <Chip size="small" variant="outlined" label={t.model} />
                  <Chip size="small" variant="outlined" label={t.provider} />
                  {t.is_shared ? <Chip size="small" label="共享" /> : null}
                  {t.has_api_key ? (
                    <Chip size="small" color="success" variant="outlined" label="已配置密钥" />
                  ) : null}
                  <Button
                    size="small"
                    onClick={async () => {
                      try {
                        const r = await testModelTemplate(t.id);
                        if (r.ok) {
                          setOk(
                            `测试通过：${r.detail}${r.models?.length ? `（可用模型：${r.models.slice(0, 3).join(", ")}）` : ""}`,
                          );
                        } else {
                          setError(`测试失败：${r.detail}`);
                        }
                      } catch (e) {
                        setError(e instanceof ApiError ? e.message : "测试失败");
                      }
                    }}
                  >
                    测试
                  </Button>
                  <Button
                    size="small"
                    sx={{ ml: "auto" }}
                    onClick={() => {
                      setEditing(t);
                      setForm({
                        name: t.name,
                        model: t.model,
                        provider: t.provider,
                        base_url: t.base_url ?? "",
                        context_length: t.context_length ?? 64000,
                        api_key: "",
                        description: t.description ?? "",
                        is_shared: t.is_shared,
                      });
                      setOpen(true);
                    }}
                  >
                    编辑
                  </Button>
                  <Button size="small" color="error" onClick={() => setConfirmId(t.id)}>
                    删除
                  </Button>
                </Stack>
                {t.base_url ? (
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                    {t.base_url}
                  </Typography>
                ) : null}
                <Typography variant="caption" color="text.secondary">
                  上下文长度：{t.context_length}
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing ? "编辑模板" : "新建模板"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="模板名"
              value={form.name}
              disabled={!!editing}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              label="模型 ID"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="gemini-2.5-flash"
            />
            <TextField
              select
              label="Provider"
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
              helperText="custom 用于 OpenAI 兼容端点（配 Base URL）"
            >
              {PROVIDERS.map((p) => (
                <MenuItem key={p} value={p}>
                  {p}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Base URL（可选）"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            />
            <TextField
              label="Context Length（上下文长度）"
              type="number"
              value={form.context_length}
              onChange={(e) => setForm({ ...form, context_length: Number(e.target.value) || 64000 })}
              helperText="Hermes 要求 >=64000；小窗口本地模型需显式声明（如 64000）"
            />
            <TextField
              label={editing?.has_api_key ? "API Key（已配置，留空不变）" : "API Key"}
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
            <TextField
              label="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            {isAdmin ? (
              <FormControlLabel
                control={
                  <Switch
                    checked={form.is_shared}
                    onChange={(e) => setForm({ ...form, is_shared: e.target.checked })}
                  />
                }
                label="共享给所有用户（只读）"
              />
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={!form.name.trim() || !form.model.trim()}
            onClick={() => void submit()}
          >
            保存
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除模型模板"
        message="已应用到 Agent 的配置不受影响（已写入 profile），但模板本身不可恢复。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          try {
            await deleteModelTemplate(confirmId);
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

export default function ModelsPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <ModelsInner />
      </AdminShell>
    </GuardedShell>
  );
}
