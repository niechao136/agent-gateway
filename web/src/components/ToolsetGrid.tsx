"use client";

import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Typography from "@mui/material/Typography";
import Tooltip from "@mui/material/Tooltip";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import LockIcon from "@mui/icons-material/Lock";
import { getToolsetCatalog, type ToolsetCatalogItem } from "@/lib/api";
import { ConfirmDialog } from "@/components/Common";

/**
 * toolset 开关网格（SPEC 6.3/6.4 + 硬约束 1）。
 *
 * 语义：开关 ON = 启用；提交时反向写入 disabled_toolsets。
 * 内置工具只能按 toolset 整体开关（hermes 实测），故无单工具开关。
 * 高危 toolset 开启需二次确认。
 */

const RISK_COLORS: Record<string, "success" | "warning" | "error" | "default"> = {
  low: "success",
  medium: "warning",
  high: "error",
};

const DANGEROUS = new Set(["terminal", "browser", "code_execution", "computer_use", "file"]);

// 场景预设（SPEC 决策）
const PRESETS: { label: string; enabled: string[] }[] = [
  { label: "只读助手", enabled: ["web", "clarify", "vision", "image_generation"] },
  {
    label: "标准",
    enabled: ["web", "clarify", "vision", "image_generation", "memory", "session_search", "skills"],
  },
  {
    label: "全开",
    enabled: [], // 全部启用
  },
];

export function ToolsetGrid({
  disabledToolsets,
  onChange,
  forcedReasons = {},
}: {
  disabledToolsets: string[];
  onChange: (next: string[]) => void;
  /** 因绑定资源而强制开启、不允许关闭的工具集 → 原因说明 */
  forcedReasons?: Record<string, string>;
}) {
  const [catalog, setCatalog] = useState<ToolsetCatalogItem[]>([]);
  const [source, setSource] = useState<"dashboard" | "static">("static");
  const [confirmItem, setConfirmItem] = useState<ToolsetCatalogItem | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getToolsetCatalog()
      .then((r) => {
        setCatalog(r.toolsets);
        setSource(r.source);
      })
      .catch(() => setCatalog([]));
  }, []);

  const enabledSet = useMemo(() => {
    const all = new Set(catalog.map((c) => c.name));
    const disabled = new Set(disabledToolsets);
    return new Set([...all].filter((n) => !disabled.has(n)));
  }, [catalog, disabledToolsets]);

  function setEnabled(name: string, on: boolean) {
    const next = new Set(disabledToolsets);
    if (on) next.delete(name);
    else next.add(name);
    onChange([...next].sort());
  }

  function trySet(item: ToolsetCatalogItem, on: boolean) {
    if (on && DANGEROUS.has(item.name)) {
      setConfirmItem(item); // 高危二次确认
      return;
    }
    setEnabled(item.name, on);
  }

  function applyPreset(p: (typeof PRESETS)[number]) {
    const keepOn = new Set(Object.keys(forcedReasons)); // 强制开启的不受影响
    if (p.enabled.length === 0 && p.label === "全开") {
      onChange([]);
      return;
    }
    const all = catalog.map((c) => c.name);
    onChange(
      all
        .filter((n) => !p.enabled.includes(n) && !keepOn.has(n))
        .sort(),
    );
  }

  if (!catalog.length) {
    return <Alert severity="info">toolset 目录加载中或不可用</Alert>;
  }

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="body2" color="text.secondary">
          场景预设：
        </Typography>
        {PRESETS.map((p) => (
          <Button key={p.label} size="small" variant="outlined" onClick={() => applyPreset(p)}>
            {p.label}
          </Button>
        ))}
        <Chip size="small" label={`目录来源: ${source}`} variant="outlined" sx={{ ml: "auto" }} />
      </Stack>

      {Object.keys(forcedReasons).length > 0 ? (
        <Alert severity="info" icon={<LockIcon fontSize="small" />}>
          以下工具集因 Agent 绑定了相关资源而自动开启且不可关闭：
          {Object.entries(forcedReasons).map(([name, reason]) => (
            <div key={name}>· {name}：{reason}</div>
          ))}
          解绑相关资源后即可自行关闭。
        </Alert>
      ) : null}

      <Stack spacing={0.5}>
        {catalog.map((item) => {
          const on = enabledSet.has(item.name);
          const risk = (item.risk as keyof typeof RISK_COLORS) ?? "default";
          return (
            <Box
              key={item.name}
              sx={{
                border: 1,
                borderColor: "divider",
                borderRadius: 2,
                px: 1.5,
                py: 1,
              }}
            >
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Switch
                  size="small"
                  checked={on}
                  onChange={(e) => trySet(item, e.target.checked)}
                />
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {item.name}
                </Typography>
                <Chip size="small" color={RISK_COLORS[risk]} label={risk} variant="outlined" />
                <Box sx={{ flexGrow: 1 }} />
                <Button
                  size="small"
                  onClick={() => setExpanded(expanded === item.name ? null : item.name)}
                  endIcon={
                    <ExpandMoreIcon
                      sx={{
                        transform: expanded === item.name ? "rotate(180deg)" : "none",
                        transition: "0.2s",
                      }}
                    />
                  }
                >
                  工具
                </Button>
              </Stack>
              <Collapse in={expanded === item.name}>
                <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap",  pt: 1 }}>
                  {item.tools.map((t) => (
                    <Chip
                      key={t}
                      size="small"
                      label={t}
                      variant="outlined"
                      sx={{ fontFamily: "monospace", fontSize: 12 }}
                    />
                  ))}
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ pt: 0.5, display: "block" }}>
                  内置工具只能按组整体开关（hermes 限制），此处仅只读展示。
                </Typography>
              </Collapse>
            </Box>
          );
        })}
      </Stack>

      <ToolsetConfirm
        item={confirmItem}
        onCancel={() => setConfirmItem(null)}
        onConfirm={() => {
          if (confirmItem) setEnabled(confirmItem.name, true);
          setConfirmItem(null);
        }}
      />
    </Stack>
  );
}

function ToolsetConfirm({
  item,
  onConfirm,
  onCancel,
}: {
  item: ToolsetCatalogItem | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!item) return null;
  return (
    <ConfirmDialog
      open
      danger
      title={`启用高危工具组 ${item.name}`}
      message={`「${item.name}」包含高危能力（shell/文件/浏览器等），\n启用后 Agent 将获得相应权限，请确认这是预期行为。`}
      confirmText="仍要启用"
      onConfirm={onConfirm}
      onClose={onCancel}
    />
  );
}
