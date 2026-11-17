"use client";

import { useCallback, useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { ApiError, listUsers, updateUser, type AdminUser, type Role } from "@/lib/api";
import { AdminShell } from "@/components/AdminShell";
import { GuardedShell } from "@/lib/authGuard";
import { ConfirmDialog, SkeletonList } from "@/components/Common";

export default function AdminUsersPage() {
  return (
    <GuardedShell require="admin">
      <AdminShell>
        <UsersView />
      </AdminShell>
    </GuardedShell>
  );
}

function UsersView() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  // 最后一名 admin 保护：降级时确认
  const [demoteId, setDemoteId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    try {
      setUsers(await listUsers());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载失败");
      setUsers([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function setRole(u: AdminUser, role: Role) {
    try {
      await updateUser(u.id, { role });
      setOk(`已将 ${u.username} 角色调整为 ${role === "admin" ? "管理员" : "用户"}`);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  async function toggleDisabled(u: AdminUser) {
    try {
      await updateUser(u.id, { disabled: !u.disabled });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  return (
    <Stack spacing={2}>
      <Typography variant="h5">用户管理</Typography>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {ok ? <Alert severity="success" onClose={() => setOk(null)}>{ok}</Alert> : null}

      {users === null ? (
        <SkeletonList rows={5} />
      ) : users.length === 0 ? (
        <Alert severity="info">还没有注册用户。</Alert>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>用户</TableCell>
              <TableCell>邮箱</TableCell>
              <TableCell>角色</TableCell>
              <TableCell align="right">会话数</TableCell>
              <TableCell>注册时间</TableCell>
              <TableCell>状态</TableCell>
              <TableCell align="center">禁用</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id} hover>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {u.username}
                  </Typography>
                  {u.display_name && u.display_name !== u.username ? (
                    <Typography variant="caption" color="text.secondary">
                      {u.display_name}
                    </Typography>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Typography variant="caption">{u.email || "—"}</Typography>
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                    <TextField
                      select
                      size="small"
                      value={u.role}
                      onChange={(e) => {
                        const role = e.target.value as Role;
                        if (role === "user" && u.role === "admin") {
                          setDemoteId(u.id); // 最后一名 admin 保护在后端 409；前端确认体验
                        } else {
                          void setRole(u, role);
                        }
                      }}
                      sx={{ width: 110 }}
                    >
                      <MenuItem value="user">用户</MenuItem>
                      <MenuItem value="admin">管理员</MenuItem>
                    </TextField>
                  </Stack>
                </TableCell>
                <TableCell align="right">{u.conversation_count}</TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {u.created_at ? new Date(u.created_at).toLocaleString() : "—"}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={u.disabled ? "已禁用" : "正常"}
                    color={u.disabled ? "error" : "success"}
                    variant={u.disabled ? "filled" : "outlined"}
                  />
                </TableCell>
                <TableCell align="center">
                  <Switch
                    size="small"
                    checked={!u.disabled}
                    onChange={() => void toggleDisabled(u)}
                    slotProps={{ input: { "aria-label": `启用 ${u.username}` } }}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <ConfirmDialog
        open={demoteId !== null}
        danger
        title="取消管理员"
        message="如果这是最后一名管理员，后端会拒绝该操作（409）。确认继续？"
        confirmText="继续"
        onConfirm={async () => {
          if (demoteId === null) return;
          await setRole(
            (users ?? []).find((u) => u.id === demoteId)!,
            "user",
          );
        }}
        onClose={() => setDemoteId(null)}
      />
    </Stack>
  );
}
