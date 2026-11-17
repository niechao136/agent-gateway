"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { getRole, getToken } from "@/lib/api";

/**
 * 首页跳转（v2 统一登录）：
 * - admin → /admin
 * - user  → /chat
 * - 未登录 → /login
 */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    router.replace(getRole() === "admin" ? "/admin" : "/chat");
  }, [router]);

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "100dvh",
      }}
    >
      <CircularProgress />
    </Box>
  );
}
