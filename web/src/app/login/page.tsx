"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import Divider from "@mui/material/Divider";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Box from "@mui/material/Box";
import { ApiError, adminLogin, login } from "@/lib/api";
import { AuthCard } from "@/components/AuthCard";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<0 | 1>(0); // 0=用户 1=管理员
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (tab === 1) {
        await adminLogin(username.trim(), password);
        router.replace("/admin");
      } else {
        await login(username.trim(), password);
        router.replace("/chat");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="登录"
      subtitle={tab === 1 ? "管理员登录后进入管理中心" : "登录后即可与 Agent 对话"}
      footer={
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
          还没有账号？
          <Link href="/register" style={{ color: "#2563eb", fontWeight: 600 }}>
            立即注册
          </Link>
        </Typography>
      }
    >
      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        <Tabs value={tab} onChange={(_, v: 0 | 1) => { setTab(v); setError(null); }} variant="fullWidth">
          <Tab label="用户" />
          <Tab label="管理员" />
        </Tabs>
      </Box>

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
            {busy ? "登录中…" : tab === 1 ? "进入管理中心" : "登录"}
          </Button>
          {tab === 1 ? (
            <>
              <Divider />
              <Typography variant="caption" color="text.secondary">
                管理员账号由部署时的 <code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code> 配置。
              </Typography>
            </>
          ) : null}
        </Stack>
      </form>
    </AuthCard>
  );
}
