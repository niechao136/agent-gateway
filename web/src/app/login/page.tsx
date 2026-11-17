"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import { ApiError, login, type Role } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";

/**
 * v2 统一登录（SPEC-v2 批次 1）：admin 与普通用户共用一个入口。
 * 登录成功后按 role 跳转：admin → /admin，user → /chat。
 */
export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await login(username.trim(), password);
      const dest = r.user.role === "admin" ? "/admin" : "/chat";
      router.replace(dest);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="登录"
      subtitle="登录后即可使用你的 Agent"
      footer={
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
          还没有账号？
          <Link href="/register" style={{ color: "#2563eb", fontWeight: 600 }}>
            立即注册
          </Link>
        </Typography>
      }
    >
      <form onSubmit={onSubmit}>
        <Stack spacing={2}>
          {error ? <Alert severity="error">{error}</Alert> : null}
          <TextField
            label="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
          <TextField
            label="密码"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          <Button type="submit" variant="contained" size="large" disabled={busy}>
            {busy ? "登录中…" : "登录"}
          </Button>
          <Box>
            <Typography variant="caption" color="text.secondary">
              管理员账号由部署时的 <code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code> 配置，
              与普通账号使用同一登录入口。
            </Typography>
          </Box>
        </Stack>
      </form>
    </AuthCard>
  );
}
