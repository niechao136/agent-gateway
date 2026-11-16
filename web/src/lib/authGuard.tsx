"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { getScope, getToken, type Scope } from "@/lib/api";

/**
 * 登录守卫（SPEC §9）。
 *
 * require: 需要的 scope；不传表示只要登录即可。
 * 返回 ready —— false 时调用方应渲染骨架，避免闪出未授权内容。
 */
export function useRequireAuth(require?: Scope): { ready: boolean } {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const scope = getScope();
    if (require && scope !== require) {
      // 有登录但 scope 不符 → 去它该去的地方
      router.replace(scope === "admin" ? "/admin" : "/chat");
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
  require?: Scope;
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
