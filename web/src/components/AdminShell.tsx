"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import Divider from "@mui/material/Divider";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import ExtensionIcon from "@mui/icons-material/Extension";
import StorageIcon from "@mui/icons-material/Storage";
import AutoStoriesIcon from "@mui/icons-material/AutoStories";
import MemoryIcon from "@mui/icons-material/Memory";
import CableIcon from "@mui/icons-material/Cable";
import HubIcon from "@mui/icons-material/Hub";
import KeyIcon from "@mui/icons-material/Key";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import ScheduleIcon from "@mui/icons-material/Schedule";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import MenuIcon from "@mui/icons-material/Menu";
import LogoutIcon from "@mui/icons-material/Logout";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import ChatIcon from "@mui/icons-material/Chat";
import SettingsIcon from "@mui/icons-material/Settings";
import { getHealth, getRole, getStoredUser, logout } from "@/lib/api";
import { useColorMode } from "@/lib/theme";
import { ChangePasswordDialog } from "@/components/ChangePasswordDialog";
import type { Role } from "@/lib/api";

const DRAWER_WIDTH = 240;

function useServiceVersion(): string {
  const [version, setVersion] = useState("");
  useEffect(() => {
    getHealth().then((h) => setVersion(h.version || "")).catch(() => undefined);
  }, []);
  return version;
}

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/admin", label: "Agent", icon: <SmartToyIcon /> },
  { href: "/admin/mcp", label: "MCP 服务器", icon: <ExtensionIcon /> },
  { href: "/admin/knowledge", label: "知识库", icon: <StorageIcon /> },
  { href: "/admin/skills", label: "自定义 Skill", icon: <AutoStoriesIcon /> },
  { href: "/admin/skills/builtin", label: "内置 Skill", icon: <MemoryIcon /> },
  { href: "/admin/models", label: "模型", icon: <MemoryIcon /> },
  { href: "/admin/connectors", label: "连接器", icon: <CableIcon /> },
  { href: "/admin/a2a", label: "A2A", icon: <HubIcon /> },
  { href: "/admin/api-keys", label: "API 密钥", icon: <KeyIcon /> },
  { href: "/admin/users", label: "用户管理", icon: <AdminPanelSettingsIcon />, adminOnly: true },
  { href: "/admin/tasks", label: "定时任务", icon: <ScheduleIcon /> },
  { href: "/admin/settings", label: "系统设置", icon: <SettingsIcon />, adminOnly: true },
];

/**
 * AdminShell（SPEC 10.2）：固定侧边栏 + 顶栏 + 主题切换 + 用户菜单。
 * 所有 /admin 页面的统一外壳。
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const muiTheme = useTheme();
  const isMobile = useMediaQuery(muiTheme.breakpoints.down("md"));
  const { mode, toggle } = useColorMode();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const serviceVersion = useServiceVersion();

  const role: Role | null = getRole();
  const user = getStoredUser();

  const items = NAV_ITEMS.filter((i) => !i.adminOnly || role === "admin");

  const drawer = (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <Toolbar>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <SmartToyIcon color="primary" />
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            Agent Gateway
          </Typography>
        </Stack>
      </Toolbar>
      <Divider />
      <List sx={{ flexGrow: 1, pt: 1 }}>
        {items.map((item) => {
          // 最长前缀匹配：避免 /admin/sk 与 /admin/skills/builtin 同时高亮。
          // /admin 同时作为 /admin/agents 编辑页的别名。
          const matches = items.filter((i) => {
            const h = i.href;
            if (h === "/admin") {
              return pathname === "/admin" || pathname.startsWith("/admin/agents");
            }
            return pathname === h || pathname.startsWith(`${h}/`);
          });
          const activeHref = matches.sort((a, b) => b.href.length - a.href.length)[0]?.href;
          const active = activeHref === item.href;
          return (
            <ListItemButton
              key={item.href}
              component={Link}
              href={item.href}
              selected={active}
              onClick={() => setDrawerOpen(false)}
              sx={{ borderRadius: 2, mx: 1, mb: 0.5 }}
            >
              <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} slotProps={{ primary: { sx: { fontSize: 14 } } }} />
            </ListItemButton>
          );
        })}
      </List>
      <Divider />
      <List>
        <ListItemButton component={Link} href="/chat" sx={{ borderRadius: 2, mx: 1, mb: 0.5 }}>
          <ListItemIcon sx={{ minWidth: 40 }}>
            <ChatIcon />
          </ListItemIcon>
          <ListItemText primary="对话" slotProps={{ primary: { sx: { fontSize: 14 } } }} />
        </ListItemButton>
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100dvh" }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          borderBottom: 1,
          borderColor: "divider",
          bgcolor: "background.paper",
          color: "text.primary",
        }}
      >
        <Toolbar>
          {isMobile ? (
            <IconButton edge="start" onClick={() => setDrawerOpen(true)} sx={{ mr: 1 }}>
              <MenuIcon />
            </IconButton>
          ) : null}
          <Typography variant="h6" sx={{ whiteSpace: "nowrap", fontSize: 16 }}>
            控制台
          </Typography>
          {serviceVersion ? (
            <Chip
              size="small"
              label={`v${serviceVersion}`}
              variant="outlined"
              sx={{
                ml: 1.5,
                height: 20,
                fontSize: 10,
                fontFamily: "monospace",
                opacity: 0.7,
              }}
            />
          ) : null}
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title={mode === "dark" ? "切换亮色" : "切换暗色"}>
            <IconButton onClick={toggle} size="small">
              {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>
          {user ? (
            <Stack direction="row" spacing={1} sx={{ alignItems: "center",  ml: 2 }}>
              <Typography variant="body2">{user.display_name || user.username}</Typography>
              <Chip
                size="small"
                label={role === "admin" ? "管理员" : "用户"}
                color={role === "admin" ? "primary" : "default"}
                variant="outlined"
              />
              <Tooltip title="修改密码">
                <IconButton size="small" onClick={() => setPasswordOpen(true)}>
                  <LockOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <IconButton
                size="small"
                onClick={() => {
                  logout();
                  router.replace("/login");
                }}
                title="退出登录"
              >
                <LogoutIcon fontSize="small" />
              </IconButton>
            </Stack>
          ) : null}
        </Toolbar>
      </AppBar>

      {isMobile ? (
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          slotProps={{ paper: { sx: { width: DRAWER_WIDTH } } }}
        >
          {drawer}
        </Drawer>
      ) : (
        <Drawer
          variant="permanent"
          sx={{
            width: DRAWER_WIDTH,
            flexShrink: 0,
            "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
          }}
        >
          {drawer}
        </Drawer>
      )}

      <Box component="main" sx={{ flexGrow: 1, p: 3, minWidth: 0 }}>
        <Toolbar />
        {children}
      </Box>
      <ChangePasswordDialog
        open={passwordOpen}
        onClose={() => setPasswordOpen(false)}
      />
    </Box>
  );
}
