#!/bin/sh
# control 容器入口：可选启动 Gemini 隧道，再运行 uvicorn。
# TUNNEL_ENABLED=1 且私钥存在时，建立 127.0.0.1:8899 -> srv-01:8899 的本地转发，
# 使模型"连接测试"（在 control 容器内发请求）也能像对话一样走隧道访问 Gemini。
set -e

KEY=/opt/data/.ssh_tunnel_key
HOST="${TUNNEL_HOST:-ubuntu@43.156.187.79}"
PORT="${TUNNEL_PORT:-8899}"

if [ "${TUNNEL_ENABLED:-0}" = "1" ]; then
    if [ -f "$KEY" ]; then
        echo "[control-entrypoint] 启动 Gemini 隧道 127.0.0.1:${PORT} -> ${HOST}:${PORT}"
        ssh -N -f \
            -i "$KEY" \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o ServerAliveInterval=30 \
            -o ExitOnForwardFailure=yes \
            -L "${PORT}:127.0.0.1:${PORT}" \
            "$HOST" || echo "[control-entrypoint] 隧道启动失败，继续（Gemini 将不可用）"
    else
        echo "[control-entrypoint] TUNNEL_ENABLED=1 但私钥 $KEY 不存在，跳过隧道" >&2
    fi
else
    echo "[control-entrypoint] TUNNEL_ENABLED!=1，跳过隧道（直连环境）"
fi

exec "$@"
