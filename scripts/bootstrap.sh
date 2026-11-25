#!/bin/sh
# 一键初始化（不依赖 make）：建目录/修权限 + 构建镜像 + 启动。
# 用法：sh scripts/bootstrap.sh
# 等价 make bootstrap；给没有安装 make 的环境（如精简测试机）使用。
set -eu

echo "[bootstrap] 1/3 创建数据目录并修正权限"
sh scripts/fix-data-perms.sh

echo "[bootstrap] 2/3 构建镜像（按 INTERNET_MODE 选镜像源）"
sh scripts/compose.sh build

echo "[bootstrap] 3/3 启动服务"
sh scripts/compose.sh up -d

echo "[bootstrap] 完成。查看状态：sh scripts/compose.sh ps"
