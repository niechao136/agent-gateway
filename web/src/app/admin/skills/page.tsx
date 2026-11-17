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
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import {
  ApiError,
  createSkill,
  deleteSkill,
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

function SkillsInner() {
  const [rows, setRows] = useState<CustomSkill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CustomSkill | null>(null);
  const [form, setForm] = useState({ name: "", description: "", content: TEMPLATE });
  const [confirmId, setConfirmId] = useState<number | null>(null);

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

  async function submit() {
    try {
      if (editing) {
        await updateSkill(editing.id, {
          description: form.description,
          content: form.content,
        });
      } else {
        await createSkill({
          name: form.name.trim(),
          description: form.description || undefined,
          content: form.content,
        });
      }
      setOpen(false);
      setOk("已保存并同步到绑定的 Agent profile");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center">
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          自定义 Skill
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => {
            setEditing(null);
            setForm({ name: "", description: "", content: TEMPLATE });
            setOpen(true);
          }}
        >
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
          hint="自定义 Skill 是给 Agent 的可复用操作指南（SKILL.md），绑定后写入 profile 的 skills/ 目录。"
        />
      ) : (
        <Stack spacing={1}>
          {rows.map((s) => (
            <Card key={s.id}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography fontWeight={700}>{s.name}</Typography>
                  {s.is_shared ? <Chip size="small" label="共享" /> : null}
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${s.bound_agents.length} 个 Agent 使用`}
                  />
                  <Button
                    size="small"
                    sx={{ ml: "auto" }}
                    onClick={() => {
                      setEditing(s);
                      setForm({
                        name: s.name,
                        description: s.description ?? "",
                        content: "",
                      });
                      // 内容需按需加载：这里简化，提示重新编辑
                      setOpen(true);
                    }}
                  >
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
              minRows={12}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              slotProps={{ input: { sx: { fontFamily: "monospace", fontSize: 13 } } }}
            />
            {editing ? (
              <Typography variant="caption" color="warning.main">
                注意：编辑时内容需重新填写（列表接口不返回正文）。
              </Typography>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>取消</Button>
          <Button
            variant="contained"
            disabled={!form.content.trim() || (!editing && !form.name.trim())}
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
