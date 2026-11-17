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
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  ApiError,
  createSkill,
  deleteSkill,
  getSkill,
  listSkills,
  updateSkill,
  type CustomSkill,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, EmptyState, SkeletonList } from "@/components/Common";

const TEMPLATE = `# 技能名称

## 何时使用
描述触发条件。

## 步骤
1. 第一步
2. 第二步
`;

// 文件类别（对应 hermes skill 目录结构与 SPEC 6.2）
const FILE_DIRS = ["references", "scripts", "templates", "assets"] as const;
type FileDir = (typeof FILE_DIRS)[number];

interface SkillFile {
  path: string; // 如 references/api.md / scripts/run.py
  content: string;
}

function SkillsInner() {
  const [rows, setRows] = useState<CustomSkill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CustomSkill | null>(null);
  const [form, setForm] = useState({ name: "", description: "", content: TEMPLATE });
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await listSkills());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate() {
    setEditing(null);
    setForm({ name: "", description: "", content: TEMPLATE });
    setFiles([]);
    setOpen(true);
  }

  async function openEdit(s: CustomSkill) {
    try {
      const detail = await getSkill(s.id); // 回填正文与文件
      setEditing(s);
      setForm({ name: s.name, description: s.description ?? "", content: detail.content });
      setFiles(
        Object.entries(detail.files ?? {}).map(([path, content]) => ({ path, content })),
      );
      setOpen(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载技能详情失败");
    }
  }

  function addFile(dir: FileDir) {
    setFiles([...files, { path: `${dir}/`, content: "" }]);
  }

  function updateFile(idx: number, patch: Partial<SkillFile>) {
    setFiles(files.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  }

  async function submit() {
    setBusy(true);
    try {
      const filesObj: Record<string, string> = {};
      for (const f of files) {
        const path = f.path.trim();
        if (path && !path.endsWith("/")) filesObj[path] = f.content;
      }
      const payload = {
        description: form.description || undefined,
        content: form.content,
        files: filesObj,
      };
      if (editing) {
        await updateSkill(editing.id, payload);
      } else {
        await createSkill({ name: form.name.trim(), ...payload });
      }
      setOpen(false);
      setOk("已保存并同步到绑定的 Agent profile");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          自定义 Skill
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          新建 Skill
        </Button>
      </Stack>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {rows === null ? (
        <SkeletonList />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<AddIcon fontSize="inherit" />}
          title="还没有自定义 Skill"
          hint="自定义 Skill 是给 Agent 的可复用操作指南（SKILL.md），可附带 references 文档与 scripts 脚本，绑定后写入 profile 的 skills/ 目录。"
        />
      ) : (
        <Stack spacing={1}>
          {rows.map((s) => (
            <Card key={s.id}>
              <CardContent>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                  <Typography sx={{ fontWeight: 700 }}>{s.name}</Typography>
                  {s.is_shared ? <Chip size="small" label="共享" /> : null}
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${s.bound_agents.length} 个 Agent 使用`}
                  />
                  <Button size="small" sx={{ ml: "auto" }} onClick={() => void openEdit(s)}>
                    编辑
                  </Button>
                  <Button size="small" color="error" onClick={() => setConfirmId(s.id)}>
                    删除
                  </Button>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {s.description || "（无描述）"}
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{editing ? `编辑 ${editing.name}` : "新建 Skill"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label="名称"
              value={form.name}
              disabled={!!editing}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <TextField
              label="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <TextField
              label="SKILL.md 内容"
              multiline
              minRows={10}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              slotProps={{ input: { sx: { fontFamily: "monospace", fontSize: 13 } } }}
            />

            {/* 附加文件：references / scripts / templates / assets */}
            <Typography variant="subtitle2">附加文件（reference 文档与执行脚本）</Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {FILE_DIRS.map((dir) => (
                <Button
                  key={dir}
                  size="small"
                  variant="outlined"
                  startIcon={<AddIcon />}
                  onClick={() => addFile(dir)}
                >
                  {dir}/
                </Button>
              ))}
            </Stack>
            <Typography variant="caption" color="text.secondary">
              scripts/ 下的脚本需要 terminal toolset 才能运行；禁用 terminal 的 Agent 会自动剥离脚本并隐藏该 Skill（SPEC 6.5）。
            </Typography>

            {files.map((f, idx) => (
              <Card key={idx} variant="outlined">
                <CardContent>
                  <Stack spacing={1}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                      <TextField
                        label="文件路径（含目录）"
                        value={f.path}
                        onChange={(e) => updateFile(idx, { path: e.target.value })}
                        placeholder="references/api.md"
                        sx={{ flexGrow: 1 }}
                      />
                      <IconButton
                        color="error"
                        onClick={() => setFiles(files.filter((_, i) => i !== idx))}
                      >
                        <DeleteIcon />
                      </IconButton>
                    </Stack>
                    <TextField
                      label="文件内容"
                      multiline
                      minRows={4}
                      value={f.content}
                      onChange={(e) => updateFile(idx, { content: e.target.value })}
                      slotProps={{ input: { sx: { fontFamily: "monospace", fontSize: 12 } } }}
                    />
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={busy || !form.content.trim() || (!editing && !form.name.trim())}
            onClick={() => void submit()}
          >
            保存
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={confirmId !== null}
        danger
        title="删除 Skill"
        message="若仍被 Agent 绑定，将强制解绑并删除对应 profile 目录。"
        confirmText="删除"
        onConfirm={async () => {
          if (confirmId === null) return;
          try {
            await deleteSkill(confirmId, true);
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

export default function SkillsPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <SkillsInner />
      </AdminShell>
    </GuardedShell>
  );
}
