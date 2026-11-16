"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { ApiError, register } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function validate(): string | null {
    if (!/^[a-zA-Z0-9_-]{3,64}$/.test(username.trim())) {
      return "用户名只能包含字母、数字、下划线和连字符，长度 3-64";
    }
    if (password.length < 8) return "密码至少 8 位";
    if (password !== confirm) return "两次输入的密码不一致";
    if (email && !/^\S+@\S+\.\S+$/.test(email)) return "邮箱格式不正确";
    return null;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setBusy(true);
    try {
      await register({
        username: username.trim(),
        password,
        ...(email.trim() ? { email: email.trim() } : {}),
      });
      router.replace("/chat");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "注册失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="注册"
      subtitle="创建账号后即可开始对话"
      footer={
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
          已有账号？
          <Link href="/login" style={{ color: "#2563eb", fontWeight: 600 }}>
            去登录
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
            helperText="3-64 位，字母/数字/下划线/连字符"
          />
          <TextField
            label="密码"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            helperText="至少 8 位"
          />
          <TextField
            label="确认密码"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
          />
          <TextField
            label="邮箱（可选）"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
          <Button type="submit" variant="contained" size="large" disabled={busy}>
            {busy ? "注册中…" : "注册"}
          </Button>
        </Stack>
      </form>
    </AuthCard>
  );
}
