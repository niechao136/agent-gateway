"use client";

import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import { useTheme } from "@mui/material/styles";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import { useColorMode } from "@/lib/theme";

export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const theme = useTheme();
  const { mode, toggle } = useColorMode();
  const dark = mode === "dark";

  return (
    <Box
      sx={{
        minHeight: "100dvh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
        // 亮/暗主题自适应背景（不再硬编码亮色渐变，修复登录页无法区分主题）
        background: dark
          ? "radial-gradient(1200px 600px at 20% -10%, #1b2440 0%, #0f1115 60%)"
          : "radial-gradient(1200px 600px at 20% -10%, #e8efff 0%, #ffffff 60%)",
      }}
    >
      <Box sx={{ position: "fixed", top: 16, right: 16 }}>
        <Tooltip title={dark ? "切换亮色" : "切换暗色"}>
          <IconButton
            onClick={toggle}
            color="inherit"
            sx={{ bgcolor: "background.paper", boxShadow: 1 }}
          >
            {dark ? <LightModeIcon /> : <DarkModeIcon />}
          </IconButton>
        </Tooltip>
      </Box>
      <Card
        sx={{
          width: "100%",
          maxWidth: 420,
          boxShadow: theme.shadows[dark ? 8 : 4],
          bgcolor: "background.paper",
        }}
      >
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          <Stack spacing={0.5} sx={{ mb: 3 }}>
            <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
              {title}
            </Typography>
            {subtitle ? (
              <Typography variant="body2" color="text.secondary">
                {subtitle}
              </Typography>
            ) : null}
          </Stack>
          {children}
          {footer ? <Box sx={{ mt: 2.5 }}>{footer}</Box> : null}
        </CardContent>
      </Card>
    </Box>
  );
}
