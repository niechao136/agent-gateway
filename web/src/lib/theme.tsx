"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  createTheme,
  ThemeProvider as MuiThemeProvider,
} from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";

type Scheme = "light" | "dark";

/**
 * ThemeRegistry（SPEC 10.3）：亮暗双主题 + 持久化 + 无闪烁。
 *
 * - 读写 localStorage "ag_color_scheme"
 * - 未设置时跟随系统 prefers-color-scheme
 * - InitColorSchemeScript 在 layout 里防 FOUC（ hydration 前就设置属性）
 */

const STORAGE_KEY = "ag_color_scheme";

type Mode = "light" | "dark" | "system";

interface ThemeContextValue {
  mode: Exclude<Mode, "system">; // 当前生效的模式
  preference: Mode; // 用户偏好（可能为 system）
  setPreference: (m: Mode) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function readStoredPreference(): Mode {
  if (typeof window === "undefined") return "system";
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

function systemScheme(): Exclude<Mode, "system"> {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function buildTheme(scheme: Scheme) {
  const dark = scheme === "dark";
  return createTheme({
    palette: {
      mode: scheme,
      primary: { main: dark ? "#60a5fa" : "#2563eb" },
      secondary: { main: dark ? "#a78bfa" : "#7c3aed" },
      success: { main: "#16a34a" },
      warning: { main: "#d97706" },
      error: { main: dark ? "#f87171" : "#dc2626" },
      // 亮色：纯白背景；暗色：深灰（非 MUI 默认蓝黑）
      background: {
        default: dark ? "#0f1115" : "#ffffff",
        paper: dark ? "#1a1d24" : "#ffffff",
      },
      text: {
        primary: dark ? "#e8eaed" : "#111827",
        secondary: dark ? "#9aa0aa" : "#5f6570",
      },
      divider: dark ? "rgba(255,255,255,0.12)" : "rgba(15,23,42,0.12)",
    },
    shape: { borderRadius: 12 },
    typography: {
      fontFamily: [
        "-apple-system",
        "BlinkMacSystemFont",
        '"Segoe UI"',
        "Roboto",
        '"Helvetica Neue"',
        '"PingFang SC"',
        '"Microsoft YaHei"',
        "sans-serif",
      ].join(","),
    },
    components: {
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
      },
      MuiTextField: {
        defaultProps: { size: "small", fullWidth: true },
      },
      MuiPaper: {
        styleOverrides: {
          root: dark
            ? { backgroundImage: "none" }
            : { backgroundImage: "none" },
        },
      },
      MuiCard: {
        defaultProps: { variant: "outlined" },
      },
      MuiTooltip: {
        defaultProps: { arrow: true },
      },
    },
  });
}

export function ThemeRegistry({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<Mode>("system");
  const [resolved, setResolved] = useState<Exclude<Mode, "system">>("light");

  // 首挂：读偏好 + 监听系统变化
  useEffect(() => {
    setPreferenceState(readStoredPreference());
    const apply = () => {
      const p = readStoredPreference();
      setResolved(p === "system" ? systemScheme() : p);
    };
    apply();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const setPreference = useCallback((m: Mode) => {
    window.localStorage.setItem(STORAGE_KEY, m);
    setPreferenceState(m);
    setResolved(m === "system" ? systemScheme() : m);
  }, []);

  const toggle = useCallback(() => {
    setPreference(resolved === "dark" ? "light" : "dark");
  }, [resolved, setPreference]);

  const value = useMemo(
    () => ({ mode: resolved, preference, setPreference, toggle }),
    [resolved, preference, setPreference, toggle],
  );

  const theme = useMemo(() => buildTheme(resolved), [resolved]);

  return (
    <ThemeContext.Provider value={value}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  );
}

export function useColorMode(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useColorMode 必须在 ThemeRegistry 内使用");
  return ctx;
}

/** 防 FOUC 的内联脚本（SSR 渲染进 <head>）。 */
export const InitColorSchemeScript = (
  <script
    dangerouslySetInnerHTML={{
      __html: `(function(){try{var k="${STORAGE_KEY}";var p=localStorage.getItem(k)||"system";var s=p==="system"?(window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):p;document.documentElement.setAttribute("data-mui-color-scheme",s);}catch(e){}})();`,
    }}
  />
);
