"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Container from "@mui/material/Container";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import Button from "@mui/material/Button";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import ChatIcon from "@mui/icons-material/Chat";
import LogoutIcon from "@mui/icons-material/Logout";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import {
  ApiError,
  getRole,
  listVisibleAgents,
  logout,
  type Agent,
} from "@/lib/api";
import { useColorMode } from "@/lib/theme";
import { GuardedShell } from "@/lib/authGuard";
import { ChangePasswordDialog } from "@/components/ChangePasswordDialog";

export default function ChatIndexPage() {
  return (
    <GuardedShell>
      <AgentPicker />
    </GuardedShell>
  );
}

function AgentPicker() {
  const router = useRouter();
  const { mode, toggle } = useColorMode();
  const isAdmin = getRole() === "admin";
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);

  useEffect(() => {
    listVisibleAgents()
      .then(setAgents)
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载失败"));
  }, []);

  return (
    <Box sx={{ minHeight: "100dvh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar>
          <Typography variant="h6" sx={{ fontWeight: 700, flexGrow: 1 }}>
            Agent Gateway
          </Typography>
          <Tooltip title={mode === "dark" ? "切换亮色" : "切换暗色"}>
            <IconButton onClick={toggle} size="small">
              {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>
          {isAdmin ? (
            <Button
              startIcon={<AdminPanelSettingsIcon />}
              onClick={() => router.push("/admin")}
              sx={{ ml: 1 }}
            >
              管理中心
            </Button>
          ) : null}
          <Button
            startIcon={<LockOutlinedIcon />}
            onClick={() => setPasswordOpen(true)}
          >
            修改密码
          </Button>
          <Button
            startIcon={<LogoutIcon />}
            onClick={() => {
              logout();
              router.replace("/login");
            }}
          >
            退出
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}  gutterBottom>
          选择一个 Agent 开始对话
        </Typography>

        {error ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        ) : null}

        {agents === null ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : agents.length === 0 ? (
          <Alert severity="info" sx={{ mt: 3 }}>
            还没有已发布的 Agent。请联系管理员在管理中心创建并发布。
          </Alert>
        ) : (
          <Grid container spacing={2} sx={{ mt: 1 }}>
            {agents.map((a) => (
              <Grid key={a.id} size={{ xs: 12, sm: 6 }}>
                <Card variant="outlined" sx={{ height: "100%" }}>
                  <CardActionArea
                    onClick={() => router.push(`/chat/${a.slug}`)}
                    sx={{ height: "100%", p: 1 }}
                  >
                    <CardContent>
                      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
                        <ChatIcon fontSize="small" color="primary" />
                        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                          {a.name}
                        </Typography>
                      </Box>
                      <Typography variant="body2" color="text.secondary">
                        {a.description || "暂无描述"}
                      </Typography>
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            ))}
          </Grid>
        )}
      </Container>
      <ChangePasswordDialog
        open={passwordOpen}
        onClose={() => setPasswordOpen(false)}
      />
    </Box>
  );
}
