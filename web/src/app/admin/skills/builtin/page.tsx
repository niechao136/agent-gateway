"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";
import {
  ApiError,
  getBuiltinSkillDetail,
  getRole,
  listAgents,
  listBuiltinSkills,
  toggleBuiltinSkill,
  type Agent,
  type BuiltinSkill,
} from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { EmptyState, SkeletonList } from "@/components/Common";

function BuiltinInner() {
  const [rows, setRows] = useState<BuiltinSkill[] | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  // 级联确认弹窗
  const [pending, setPending] = useState<{ skill: BuiltinSkill; enabled: boolean } | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<{ name: string; content: string } | null>(null);

  const isAdmin = getRole() === "admin";

  const load = useCallback(async () => {
    try {
      const [skills, ags] = await Promise.all([
        listBuiltinSkills().catch(() => [] as BuiltinSkill[]),
        listAgents().catch(() => [] as Agent[]),
      ]);
      setRows(skills);
      setAgents(ags);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function tryToggle(skill: BuiltinSkill, enabled: boolean) {
    if (!isAdmin) {
      setError("内置技能启停需要管理员");
      return;
    }
    if (!enabled) {
      // 先尝试直接禁用；409 = 需要级联确认
      try {
        const r = await toggleBuiltinSkill(skill.name, false, []);
        setOk(`已禁用 ${skill.name}（${r.agents.filter((a) => a.ok).length} 个 Agent 同步）`);
        await load();
        return;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setChecked(new Set(agents.map((a) => a.id)));
          setPending({ skill, enabled });
          return;
        }
        setError(e instanceof ApiError ? e.message : "操作失败");
        return;
      }
    }
    try {
      await toggleBuiltinSkill(skill.name, true, []);
      setOk(`已启用 ${skill.name}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  async function confirmCascade() {
    if (!pending) return;
    try {
      const r = await toggleBuiltinSkill(
        pending.skill.name,
        pending.enabled,
        [...checked],
      );
      setOk(
        `${pending.skill.name}: ${r.agents.filter((a) => a.ok).length} 个 Agent 同步成功${
          r.errors.length ? `，${r.errors.length} 个失败` : ""
        }`,
      );
      setPending(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5">内置 Skill</Typography>
      <Typography variant="body2" color="text.secondary">
        hermes 自带技能，此处为只读代理 + 全局启停。禁用会影响绑定了它的 Agent，需要级联确认。
      </Typography>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {rows === null ? (
        <SkeletonList />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Box>📦</Box>}
          title="内置技能列表不可用"
          hint="hermes dashboard 未运行或没有 /api/skills 端点。"
        />
      ) : (
        <Stack spacing={1}>
          {rows.map((s) => (
            <Card key={s.name}>
              <CardContent>
                <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
                  <Switch
                    checked={s.enabled}
                    onChange={(e) => void tryToggle(s, e.target.checked)}
                    disabled={!isAdmin}
                  />
                  <Box sx={{ flexGrow: 1 }}>
                    <Typography sx={{ fontWeight: 700 }}>{s.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {s.description || "（无描述）"}
                    </Typography>
                  </Box>
                  <Button
                    size="small"
                    onClick={() =>
                      getBuiltinSkillDetail(s.name)
                        .then((d) =>
                          setDetail({ name: d.name, content: d.content || "（无正文）" }),
                        )
                        .catch(() => setDetail({ name: s.name, content: "（读取失败）" }))
                    }
                  >
                    详情
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}

      {/* 内置技能详情 */}
      <Dialog
        open={detail !== null}
        onClose={() => setDetail(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>{detail?.name ?? ""}</DialogTitle>
        <DialogContent dividers>
          <Box
            component="pre"
            sx={{
              m: 0,
              fontFamily: "monospace",
              fontSize: 12,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {detail?.content ?? ""}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetail(null)}>关闭</Button>
        </DialogActions>
      </Dialog>

      {/* 级联禁用确认 */}
      <Dialog open={pending !== null} onClose={() => setPending(null)} maxWidth="xs" fullWidth>
        <DialogTitle>级联禁用 {pending?.skill.name}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            勾选要对其禁用该技能的 Agent（全选为默认）：
          </Typography>
          {agents.map((a) => (
            <FormControlLabel
              key={a.id}
              control={
                <Checkbox
                  checked={checked.has(a.id)}
                  onChange={(e) => {
                    const next = new Set(checked);
                    if (e.target.checked) next.add(a.id);
                    else next.delete(a.id);
                    setChecked(next);
                  }}
                />
              }
              label={a.name}
            />
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPending(null)}>取消</Button>
          <Button variant="contained" color="error" onClick={() => void confirmCascade()}>
            确认禁用（{checked.size}）
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export default function BuiltinSkillsPage() {
  return (
    <GuardedShell>
      <AdminShell>
        <BuiltinInner />
      </AdminShell>
    </GuardedShell>
  );
}
