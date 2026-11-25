#!/bin/sh
# 统一数据目录权限。在任何目录调用都能正确解析相对路径（锚定仓库根）。
# 需 sudo 才能 chown 给容器用户；无 sudo 时只建目录并给出提示。
set -e

# 锚定到仓库根：脚本位于 <root>/scripts/，与 docker-compose.yml 的相对路径基准一致
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT"

# 显式传入的环境变量优先；未设置的才从 .env 的对应键取（只读需要的键，不 source 整个文件）
env_get() {
    # $1=key  $2=default
    eval "cur=\${$1:-}"
    if [ -n "$cur" ]; then printf '%s' "$cur"; return; fi
    if [ -f .env ]; then
        val=$(grep -E "^[[:space:]]*$1[[:space:]]*=" .env 2>/dev/null | tail -1 | sed -e "s/^[^=]*=//" -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//')
        if [ -n "$val" ]; then printf '%s' "$val"; return; fi
    fi
    printf '%s' "$2"
}

DATA_DIR=$(env_get DATA_DIR "./data")
DATA_UID=$(env_get DATA_UID "1000")
DATA_GID=$(env_get DATA_GID "1000")

# 相对路径按仓库根解析（与 docker compose 的规则一致）
case "$DATA_DIR" in
    /*) ABS_DIR="$DATA_DIR" ;;
    *)  ABS_DIR="$ROOT/${DATA_DIR#./}" ;;
esac

mkdir -p "$ABS_DIR/hermes" "$ABS_DIR/postgres"

if [ "$(id -u)" = "0" ]; then
    chown -R "$DATA_UID:$DATA_GID" "$ABS_DIR"
elif sudo -n true 2>/dev/null; then
    sudo -n chown -R "$DATA_UID:$DATA_GID" "$ABS_DIR"
else
    echo "[fix-data-perms] 无法自动 chown（非 root 且无免密 sudo）。" >&2
    echo "[fix-data-perms] 请手动执行：sudo chown -R $DATA_UID:$DATA_GID $ABS_DIR" >&2
    echo "[fix-data-perms] 目录已创建，继续启动（若属主不符，control 写 profile 可能报 PermissionError）。" >&2
fi

echo "[fix-data-perms] 就绪：$ABS_DIR (owner target $DATA_UID:$DATA_GID)"
