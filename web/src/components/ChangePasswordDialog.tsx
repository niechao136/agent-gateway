"use client";

import { useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import { ApiError, changePassword, clearSession } from "@/lib/api";

/** 修改当前登录用户密码；成功后要求重新登录（旧 token 虽有效但统一重登更清晰）。 */
export function ChangePasswordDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    if (next !== confirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      setOk(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "修改失败");
    } finally {
      setBusy(false);
    }
  }

  function finish() {
    // 密码已改，清除会话并跳登录
    clearSession();
    window.location.href = "/login";
  }

  return (
    <Dialog open={open} onClose={ok ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>修改密码</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {ok ? (
            <Alert severity="success">
              密码修改成功，请重新登录。
            </Alert>
          ) : (
            <>
              {error ? <Alert severity="error">{error}</Alert> : null}
              <TextField
                label="原密码"
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
              />
              <TextField
                label="新密码（至少 8 位）"
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
              />
              <TextField
                label="确认新密码"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        {ok ? (
          <Button variant="contained" onClick={finish}>
            去登录
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>取消</Button>
            <Button
              variant="contained"
              disabled={busy || !current || !next || next.length < 8}
              onClick={() => void submit()}
            >
              确认修改
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
