"use client";

import { useRouter } from "next/navigation";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import LogoutIcon from "@mui/icons-material/Logout";
import ChatIcon from "@mui/icons-material/Chat";
import { logout } from "@/lib/api";

export type AdminSection = "agents" | "users" | "models";

/**
 * 管理中心顶部导航。
 * 放在 Toolbar 右侧，配合各页面的标题使用。
 */
export function AdminNav({ current }: { current: AdminSection }) {
  const router = useRouter();

  return (
    <>
      <Button
        onClick={() => router.push("/admin")}
        variant={current === "agents" ? "text" : "text"}
        size="small"
        sx={{
          mr: 1,
          fontWeight: current === "agents" ? 700 : 400,
          textDecoration: current === "agents" ? "underline" : "none",
          textUnderlineOffset: 4,
        }}
      >
        Agent
      </Button>
      <Button
        onClick={() => router.push("/admin/users")}
        size="small"
        sx={{
          mr: 1,
          fontWeight: current === "users" ? 700 : 400,
          textDecoration: current === "users" ? "underline" : "none",
          textUnderlineOffset: 4,
        }}
      >
        用户
      </Button>
      <Button
        onClick={() => router.push("/admin/models")}
        size="small"
        sx={{
          mr: 2,
          fontWeight: current === "models" ? 700 : 400,
          textDecoration: current === "models" ? "underline" : "none",
          textUnderlineOffset: 4,
        }}
      >
        模型
      </Button>
      <Button
        startIcon={<ChatIcon />}
        size="small"
        onClick={() => router.push("/chat")}
        sx={{ mr: 1 }}
      >
        去对话
      </Button>
      <IconButton
        aria-label="退出"
        onClick={() => {
          logout();
          router.replace("/login");
        }}
      >
        <LogoutIcon />
      </IconButton>
    </>
  );
}
