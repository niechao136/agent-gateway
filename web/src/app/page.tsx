"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { getScope, getToken } from "@/lib/api";

/**
 * 首页：规格要求「首页改为管理中心」（SPEC §2.2）。
 *
 * - 已登录（admin） → /admin
 * - 已登录（user）  → /chat
 * - 未登录          → /login
 */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    router.replace(getScope() === "admin" ? "/admin" : "/chat");
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
