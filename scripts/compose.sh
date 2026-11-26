#!/bin/sh
# 唯一的 compose 入口。所有环境（本地/服务器/其他）都用这一个脚本。
#
# 它做三件事：
#   1. 读取 .env（INTERNET_MODE 与用户显式设置）
#   2. 按 INTERNET_MODE 派生镜像源默认值 —— 只在用户没显式设置时生效
#   3. 调用 docker compose（固定 --env-file .env --profile full）
#
# 用法：
#   ./scripts/compose.sh deploy          # ★ 推荐：build → 强制重建全部容器 → 等健康
#   ./scripts/compose.sh up -d --no-build
#   ./scripts/compose.sh build
#   ./scripts/compose.sh restart hermes
#   ./scripts/compose.sh config          # 查看最终渲染配置
#
# 为什么需要 deploy：
#   单纯 `build` + `up -d --no-build` 时，compose 若判定容器配置未变，
#   不会替换旧容器 —— nginx 不会重载新配置、web 不会用新镜像。
#   必须 `--force-recreate` 才能让配置/镜像变更真正生效。
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

# deploy：构建 → 强制重建全部 → 等待健康。避免"构建了但容器没换"的坑。
if [ "${1:-}" = "deploy" ]; then
    shift
    COMPOSE="docker compose --env-file .env --profile full"

    echo "[deploy] 1/3 构建镜像…"
    $COMPOSE build

    echo "[deploy] 2/3 强制重建全部容器…"
    $COMPOSE up -d --force-recreate --remove-orphans

    echo "[deploy] 3/3 等待健康检查…"
    # 最多等 180 秒；只等带 healthcheck 的容器，其他容器只要 up 即可。
    _i=0
    while [ "$_i" -lt 60 ]; do
        _unhealthy=$(docker ps --format '{{.Names}} {{.Status}}' \
            | grep '^ag-' | grep -E 'Starting|health: starting|unhealthy' || true)
        if [ -z "$_unhealthy" ]; then
            break
        fi
        _i=$((_i + 1))
        sleep 3
    done

    echo "[deploy] 完成，当前状态："
    docker ps --format '{{.Names}} {{.Status}}' | grep '^ag-' || true
    _bad=$(docker ps --format '{{.Names}} {{.Status}}' \
        | grep '^ag-' | grep -v 'Up ' || true)
    if [ -n "$_bad" ]; then
        echo "[deploy] ⚠ 以下容器未正常运行：" >&2
        echo "$_bad" >&2
        exit 1
    fi
    exit 0
fi

exec docker compose --env-file .env --profile full "$@"
