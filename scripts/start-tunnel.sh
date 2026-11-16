#!/bin/sh
# 启动 Gemini 反向代理的 SSH 隧道。
#
# 背景（见 SPEC §11.9.9）：
#   本地无法直连 generativelanguage.googleapis.com，需要经新加坡服务器中转。
#   服务器上的 gemini-proxy 容器（8899）反向代理到 Google。
#   这里在 hermes 容器内起一条 SSH 本地转发：127.0.0.1:8899 → 服务器 8899。
#
# 用法：由 s6 或 entrypoint 调用，容器启动时自动执行。
#   手动执行：docker exec -u hermes ag-hermes /opt/data/start-tunnel.sh
set -u

KEY=/opt/data/.ssh_tunnel_key
HOST="${TUNNEL_HOST:-ubuntu@43.156.187.79}"
PORT="${TUNNEL_PORT:-8899}"
LOG=/tmp/tunnel.log

if [ ! -f "$KEY" ]; then
    echo "[tunnel] 未找到私钥 $KEY，跳过"
    exit 0
fi

# 已有隧道则先清理
if pgrep -f "ssh -i $KEY -N" >/dev/null 2>&1; then
    echo "[tunnel] 已存在，跳过"
    exit 0
fi

cp "$KEY" /tmp/.tk 2>/dev/null || true
chmod 600 /tmp/.tk 2>/dev/null || true

nohup ssh -i /tmp/.tk -N \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:${PORT}:127.0.0.1:${PORT}" \
    "$HOST" > "$LOG" 2>&1 &

sleep 5

if pgrep -f "ssh -i /tmp/.tk -N" >/dev/null 2>&1; then
    echo "[tunnel] 已建立 127.0.0.1:${PORT} -> ${HOST}:${PORT}"
else
    echo "[tunnel] 建立失败，日志："
    tail -5 "$LOG" 2>/dev/null
fi
