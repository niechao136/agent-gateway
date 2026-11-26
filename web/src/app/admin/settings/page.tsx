"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import {
  listSettings,
  updateSettings,
  type SystemSetting,
} from "@/lib/api";

export default function SettingsPage() {
  const [items, setItems] = useState<SystemSetting[]>([]);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSettings();
      setItems(data);
      setDraft(Object.fromEntries(data.map((i) => [i.key, i.value])));
    } catch (e) {
      setMsg(`加载失败：${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      const changed = Object.fromEntries(
        items
          .filter((i) => draft[i.key] !== i.value)
          .map((i) => [i.key, draft[i.key]]),
      );
      if (Object.keys(changed).length === 0) {
        setMsg("没有需要保存的变更");
        setSaving(false);
        return;
      }
      const r = await updateSettings(changed);
      setMsg(
        `已保存 ${r.updated.length} 项；影响 ${r.affected_profiles} 个 Agent（工具集/技能类配置在下次下发或重启后生效）`,
      );
      await load();
    } catch (e) {
      setMsg(`保存失败：${String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <GuardedShell require="admin">
      <AdminShell>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Typography variant="h5" sx={{ flexGrow: 1 }}>系统设置</Typography>
            <Button variant="contained" onClick={() => void save()} disabled={saving}>
              {saving ? <CircularProgress size={20} /> : "保存"}
            </Button>
          </Stack>
          {msg ? <Alert severity="info">{msg}</Alert> : null}
          {loading ? (
            <CircularProgress />
          ) : (
            items.map((item) => (
              <Card key={item.key}>
                <CardContent>
                  <Stack
                    direction="row"
                    spacing={2}
                    sx={{ alignItems: "center", justifyContent: "space-between" }}
                  >
                    <Box sx={{ flexGrow: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                        <Typography variant="subtitle1">{item.key}</Typography>
                        <Chip size="small" label={item.type} variant="outlined" />
                        {draft[item.key] !== item.value ? (
                          <Chip size="small" color="warning" label="未保存" />
                        ) : null}
                      </Stack>
                      <Typography variant="caption" color="text.secondary">
                        {item.description}
                      </Typography>
                    </Box>
                    {item.type === "bool" ? (
                      <Switch
                        checked={Boolean(draft[item.key])}
                        onChange={(e) =>
                          setDraft((d) => ({ ...d, [item.key]: e.target.checked }))
                        }
                      />
                    ) : (
                      <TextField
                        type="number"
                        size="small"
                        value={String(draft[item.key] ?? "")}
                        onChange={(e) =>
                          setDraft((d) => ({
                            ...d,
                            [item.key]: Number(e.target.value),
                          }))
                        }
                        slotProps={{
                          htmlInput: { min: 0, style: { width: 90, textAlign: "right" } },
                        }}
                      />
                    )}
                  </Stack>
                </CardContent>
              </Card>
            ))
          )}
        </Stack>
      </AdminShell>
    </GuardedShell>
  );
}
