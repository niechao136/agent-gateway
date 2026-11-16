"use client";

import { useEffect, useMemo, useState } from "react";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Switch from "@mui/material/Switch";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { ApiError, listAgentSkills, toggleAgentSkill, type AgentSkill } from "@/lib/api";

/**
 * Agent 的 Skill 开关面板。
 *
 * 语义（重要）：hermes 的 skill 是 profile 级的**开关**，不是复制文件。
 * 启用后该 Agent 的会话就能看到这个 skill。
 */
export function SkillsPanel({ agentId }: { agentId: number }) {
  const [skills, setSkills] = useState<AgentSkill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    listAgentSkills(agentId)
      .then(setSkills)
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载 skills 失败"));
  }, [agentId]);

  const groups = useMemo(() => {
    const list = (skills ?? []).filter(
      (s) =>
        !q.trim() ||
        s.name.toLowerCase().includes(q.toLowerCase()) ||
        (s.description ?? "").toLowerCase().includes(q.toLowerCase()),
    );
    const map = new Map<string, AgentSkill[]>();
    for (const s of list) {
      const k = s.category || "其他";
      const arr = map.get(k) ?? [];
      arr.push(s);
      map.set(k, arr);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [skills, q]);

  async function toggle(s: AgentSkill) {
    if (s.locked) return;
    setPending(s.name);
    // 乐观更新，失败则回滚
    setSkills((prev) =>
      prev ? prev.map((x) => (x.name === s.name ? { ...x, enabled: !x.enabled } : x)) : prev,
    );
    try {
      const updated = await toggleAgentSkill(agentId, s.name, !s.enabled);
      setSkills((prev) =>
        prev ? prev.map((x) => (x.name === updated.name ? updated : x)) : prev,
      );
    } catch (e) {
      setSkills((prev) =>
        prev ? prev.map((x) => (x.name === s.name ? { ...x, enabled: s.enabled } : x)) : prev,
      );
      setError(e instanceof ApiError ? e.message : "切换失败");
    } finally {
      setPending(null);
    }
  }

  const enabledCount = (skills ?? []).filter((s) => s.enabled).length;

  if (skills === null && !error) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  return (
    <Box>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1.5 }}>
        <Typography variant="body2" color="text.secondary">
          共 {skills?.length ?? 0} 个技能，已启用 {enabledCount} 个
        </Typography>
        <TextField
          size="small"
          placeholder="搜索技能…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          sx={{ maxWidth: 260, ml: "auto" }}
        />
      </Box>

      {groups.length === 0 ? (
        <Alert severity="info">没有匹配的技能。</Alert>
      ) : (
        groups.map(([category, items]) => (
          <Accordion key={category} defaultExpanded={category === "其他"} disableGutters>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {category}
              </Typography>
              <Chip
                size="small"
                label={`${items.filter((i) => i.enabled).length}/${items.length}`}
                sx={{ ml: 1 }}
                variant="outlined"
              />
            </AccordionSummary>
            <AccordionDetails sx={{ pt: 0 }}>
              {items.map((s) => (
                <Box
                  key={s.name}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    gap: 1,
                    py: 0.75,
                    borderBottom: 1,
                    borderColor: "divider",
                    "&:last-of-type": { borderBottom: 0 },
                  }}
                >
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {s.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap component="div">
                      {s.description || "—"}
                    </Typography>
                  </Box>
                  {s.locked ? <Chip size="small" label="锁定" /> : null}
                  <Switch
                    size="small"
                    checked={s.enabled}
                    disabled={s.locked || pending === s.name}
                    onChange={() => void toggle(s)}
                    slotProps={{ input: { "aria-label": `启用 ${s.name}` } }}
                  />
                </Box>
              ))}
            </AccordionDetails>
          </Accordion>
        ))
      )}
    </Box>
  );
}
