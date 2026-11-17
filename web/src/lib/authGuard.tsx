"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { getRole, getToken, type Role } from "@/lib/api";

/**
 * 登录守卫（v2）。
 *
 * require: 需要的 role；不传表示只要登录即可。
 * v2 变化：管理页不再拒绝普通用户在客户端层面拦截——后端才是权威；
 * 客户端守卫只做体验优化（无权限跳到该用户该去的地方）。
 */
export function useRequireAuth(require?: Role): { ready: boolean } {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const role = getRole();
    if (require && role !== require) {
      router.replace(role === "admin" ? "/admin" : "/chat");
      return;
    }
    setReady(true);
  }, [router, require]);

  return { ready };
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "60dvh",
      }}
    >
      {children}
    </Box>
  );
}

export function GuardedShell({
  require,
  children,
}: {
  require?: Role;
  children: React.ReactNode;
}) {
  const { ready } = useRequireAuth(require);
  if (!ready) {
    return (
      <AuthGate>
        <CircularProgress />
      </AuthGate>
    );
  }
  return <>{children}</>;
}
