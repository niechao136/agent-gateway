"use client";

import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import type { AuthType } from "@/lib/api";

/**
 * 五方式鉴权字段组（SPEC-v2 批次 2 决策 8）。
 *
 * - 切换 auth_type 时保留已填 token/auth_name（决策：切鉴权方式保留已填密钥）
 * - 编辑态回显 hasExistingToken 提示（token 不回明文）
 */
export function AuthFields({
  authType,
  token,
  authName,
  hasExistingToken = false,
  authTypes,
  onChange,
}: {
  authType: AuthType;
  token: string;
  authName: string;
  hasExistingToken?: boolean;
  authTypes: readonly AuthType[];
  onChange: (patch: { auth_type?: AuthType; token?: string; auth_name?: string }) => void;
}) {
  const needToken = authType !== "none";
  const needName = authType === "header" || authType === "query";

  return (
    <Stack spacing={2}>
      <TextField
        select
        label="鉴权方式"
        value={authType}
        onChange={(e) => onChange({ auth_type: e.target.value as AuthType })}
        helperText={{
          none: "不鉴权",
          bearer: "Authorization: Bearer <token>",
          header: "自定义 Header：<auth_name>: <token>",
          query: "URL 参数：<auth_name>=<token>",
          basic: "Basic 认证（auth_name 为用户名，token 为密码）",
        }[authType]}
      >
        {authTypes.map((t) => (
          <MenuItem key={t} value={t}>
            {t}
          </MenuItem>
        ))}
      </TextField>

      {needToken ? (
        <TextField
          label={hasExistingToken ? "Token（已配置，留空保持不变）" : "Token"}
          type="password"
          value={token}
          onChange={(e) => onChange({ token: e.target.value })}
          placeholder={hasExistingToken ? "••••••" : undefined}
        />
      ) : null}

      {needName ? (
        <TextField
          label={authType === "header" ? "Header 名" : "Query 参数名"}
          value={authName}
          onChange={(e) => onChange({ auth_name: e.target.value })}
          placeholder={authType === "header" ? "X-Api-Key" : "api_key"}
        />
      ) : null}

      {authType === "basic" ? (
        <Typography variant="caption" color="text.secondary">
          Basic 认证：Token 填密码，auth_name 填用户名。
        </Typography>
      ) : null}
    </Stack>
  );
}
