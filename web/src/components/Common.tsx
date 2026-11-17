"use client";

import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";

/** 通用确认对话框。 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = "确认",
  danger = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ whiteSpace: "pre-line" }}>{message}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          onClick={() => {
            onConfirm();
            onClose();
          }}
          color={danger ? "error" : "primary"}
          variant="contained"
          autoFocus
        >
          {confirmText}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** 空状态（图标 + 说明 + 可选主操作）。 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        py: 10,
        gap: 1.5,
        textAlign: "center",
      }}
    >
      <Box sx={{ fontSize: 48, opacity: 0.5 }}>{icon}</Box>
      <Typography variant="h6">{title}</Typography>
      {hint ? (
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420 }}>
          {hint}
        </Typography>
      ) : null}
      {action}
    </Box>
  );
}

/** 列表加载骨架。 */
export function SkeletonList({ rows = 3 }: { rows?: number }) {
  return (
    <Stack spacing={2} sx={{ py: 2 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} variant="rounded" height={72} />
      ))}
    </Stack>
  );
}

const STATUS_COLORS: Record<string, string> = {
  connected: "success.main",
  connecting: "warning.main",
  error: "error.main",
  stopped: "text.disabled",
  idle: "text.disabled",
};

/** 状态圆点（连接器等运行时状态）。 */
export function StatusDot({ state, label }: { state: string; label?: string }) {
  const color = STATUS_COLORS[state] ?? "text.disabled";
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Box
        sx={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          bgcolor: color,
          flexShrink: 0,
        }}
      />
      {label ? <Typography variant="body2">{label}</Typography> : null}
    </Stack>
  );
}
