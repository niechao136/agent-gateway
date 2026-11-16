"use client";

import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import {
  ApiError,
  applyModelTemplate,
  getEffectiveModel,
  listModelTemplates,
  type ModelTemplate,
} from "@/lib/api";

/**
 * 模型模板应用面板。
 *
 * 语义：把模板的 model/provider/base_url/api_key 写入该 Agent 的 profile
 * config.yaml 的 model 段（其他段保留）。
 */
export function ModelPanel({ agentId }: { agentId: number }) {
  const [templates, setTemplates] = useState<ModelTemplate[] | null>(null);
  const [effective, setEffective] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    listModelTemplates()
      .then(setTemplates)
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载模板失败"));
    getEffectiveModel(agentId)
      .then((r) => setEffective(r.model))
      .catch(() => setEffective({}));
  }, [agentId]);

  async function apply(id: number, name: string) {
    setBusy(id);
    setOk(null);
    setError(null);
    try {
      await applyModelTemplate(agentId, id);
      const fresh = await getEffectiveModel(agentId);
      setEffective(fresh.model);
      setOk(`已应用模板「${name}」。新会话生效。`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "应用失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Box>
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

      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        当前生效的模型配置（来自 profile 的 config.yaml）：
      </Typography>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
        {effective && Object.keys(effective).length > 0 ? (
          Object.entries(effective).map(([k, v]) => (
            <Chip
              key={k}
              size="small"
              variant="outlined"
              label={`${k}: ${String(v)}`}
            />
          ))
        ) : (
          <Typography variant="caption" color="text.secondary">
            未读取到（profile 可能不存在）
          </Typography>
        )}
      </Box>

      {templates === null ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={22} />
        </Box>
      ) : templates.length === 0 ? (
        <Alert severity="info">
          还没有模型模板。先到「模型」页创建，或直接在下方手填 model 字段。
        </Alert>
      ) : (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {templates.map((t) => (
            <Box
              key={t.id}
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1,
                p: 1.25,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
              }}
            >
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {t.name}
                </Typography>
                <Typography variant="caption" color="text.secondary" component="div" noWrap>
                  {t.model} · {t.provider}
                  {t.base_url ? ` · ${t.base_url}` : ""}
                </Typography>
              </Box>
              <Button
                size="small"
                variant="outlined"
                disabled={busy === t.id}
                onClick={() => void apply(t.id, t.name)}
              >
                {busy === t.id ? "应用中…" : "应用"}
              </Button>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
