#!/bin/sh
# 自动创建数据目录并统一属主。
#
# 由 Makefile 的 up/build 目标在 docker compose 之前自动调用；也可手动运行：
#   DATA_DIR=/path/to/data DATA_UID=1002 DATA_GID=1003 ./scripts/fix-data-perms.sh
#
# 设计目标：本地 / 服务器 / 其他环境用同一套逻辑，消除"目录不存在"和
# "原子写临时文件 PermissionError"两类问题。
set -eu

DATA_DIR="${DATA_DIR:-./data}"
DATA_UID="${DATA_UID:-1000}"
DATA_GID="${DATA_GID:-1000}"

# 目录不存在时自动创建（hermes 与 postgres 两个子目录）
mkdir -p "$DATA_DIR/hermes" "$DATA_DIR/postgres"

# chown 需要权限。有 sudo 且非 root 时用 sudo；root 直接执行；
# 都没有（如某些 CI / Windows git-bash 直接跑）则给出明确提示而非静默失败。
if [ "$(id -u)" -eq 0 ]; then
    chown -R "${DATA_UID}:${DATA_GID}" "$DATA_DIR"
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo chown -R "${DATA_UID}:${DATA_GID}" "$DATA_DIR"
else
    echo "[fix-data-perms] 无法自动 chown（非 root 且无免密 sudo）。" >&2
    echo "[fix-data-perms] 请手动执行：sudo chown -R ${DATA_UID}:${DATA_GID} ${DATA_DIR}" >&2
    echo "[fix-data-perms] 目录已创建，继续启动（若属主不符，control 写 profile 可能报 PermissionError）。" >&2
    exit 0
fi

echo "[fix-data-perms] $DATA_DIR 已就绪，属主 ${DATA_UID}:${DATA_GID}"
