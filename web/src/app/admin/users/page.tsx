"use client";

import { useCallback, useEffect, useState } from "react";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Box from "@mui/material/Box";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Switch from "@mui/material/Switch";
import { ApiError, listUsers, updateUser, type AdminUser } from "@/lib/api";
import { GuardedShell } from "@/lib/authGuard";
import { AdminNav } from "@/components/AdminNav";

export default function AdminUsersPage() {
  return (
    <GuardedShell require="admin">
      <UsersView />
    </GuardedShell>
  );
}

function UsersView() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  async function toggle(u: AdminUser) {
    try {
      await updateUser(u.id, { disabled: !u.disabled });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作失败");
    }
  }

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <AppBar
        position="sticky"
        color="inherit"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: "divider" }}
      >
        <Toolbar>
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            管理中心
          </Typography>
          <AdminNav current="users" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>
          用户
        </Typography>

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}

        {users === null ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : users.length === 0 ? (
          <Alert severity="info">还没有注册用户。</Alert>
        ) : (
          <Table size="small" sx={{ bgcolor: "background.paper" }}>
            <TableHead>
              <TableRow>
                <TableCell>用户名</TableCell>
                <TableCell>邮箱</TableCell>
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
                      onChange={() => void toggle(u)}
                      slotProps={{ input: { "aria-label": `启用 ${u.username}` } }}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Container>
    </Box>
  );
}
