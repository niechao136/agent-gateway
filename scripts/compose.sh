#!/bin/sh
# 唯一的 compose 入口。所有环境（本地/服务器/其他）都用这一个脚本。
#
# 它做三件事：
#   1. 读取 .env（INTERNET_MODE 与用户显式设置）
#   2. 按 INTERNET_MODE 派生镜像源默认值 —— 只在用户没显式设置时生效
#   3. 调用 docker compose（固定 --env-file .env --profile full）
#
# 用法：
#   ./scripts/compose.sh up -d --no-build
#   ./scripts/compose.sh build
#   ./scripts/compose.sh restart hermes
#   ./scripts/compose.sh config          # 查看最终渲染配置
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
    echo "[compose] 缺少 .env，请先：cp .env.example .env" >&2
    exit 1
fi

# 读取 .env（KEY=VALUE 形式，可安全 source）
# shellcheck disable=SC1091
set -a
. ./.env
set +a

# 镜像源派生：INTERNET_MODE=direct → 官方；cn → 国内镜像。
# 关键：只有用户没有显式设置时才用派生值（用户 .env 里的值优先）。
case "${INTERNET_MODE:-cn}" in
    direct)
        DEFAULT_PIP=https://pypi.org/simple
        DEFAULT_NPM=https://registry.npmjs.org
        DEFAULT_TUNNEL=0
        ;;
    cn)
        DEFAULT_PIP=https://pypi.tuna.tsinghua.edu.cn/simple
        DEFAULT_NPM=https://registry.npmmirror.com
        DEFAULT_TUNNEL=0
        ;;
    *)
        echo "[compose] INTERNET_MODE 只能是 direct 或 cn，当前=${INTERNET_MODE}" >&2
        exit 1
        ;;
esac

[ -n "${PIP_INDEX_URL:-}" ] || PIP_INDEX_URL="$DEFAULT_PIP"
[ -n "${NPM_REGISTRY:-}" ] || NPM_REGISTRY="$DEFAULT_NPM"
[ -n "${TUNNEL_ENABLED:-}" ] || TUNNEL_ENABLED="$DEFAULT_TUNNEL"

export PIP_INDEX_URL NPM_REGISTRY TUNNEL_ENABLED

# 走 SOCKS/HTTP 代理的环境（测试机即此类）：BuildKit 的 remote metadata 拉取
# 不读 daemon 代理，会 connection reset；legacy builder 走 daemon 代理，稳定。
# 可用 DOCKER_BUILDKIT=1 显式覆盖。
[ -n "${DOCKER_BUILDKIT:-}" ] || DOCKER_BUILDKIT=0
export DOCKER_BUILDKIT

echo "[compose] INTERNET_MODE=${INTERNET_MODE} PIP=${PIP_INDEX_URL} NPM=${NPM_REGISTRY} TUNNEL=${TUNNEL_ENABLED} BUILDKIT=${DOCKER_BUILDKIT}"

exec docker compose --env-file .env --profile full "$@"
