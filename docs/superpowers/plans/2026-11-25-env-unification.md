# 环境配置统一实施计划

## 目标
- `INTERNET_MODE` 两档：`direct`（外网直连）/ `cn`（国内），自动派生默认镜像源，且允许 env 覆盖。
- 删除 `docker-compose.override.yml`，user/mem 由主 compose + 环境变量控制。
- `scripts/fix-data-perms.sh` 自动运行、自动创建目录；统一 DATA_DIR/DATA_UID/DATA_GID。
- `.gitattributes` 锁定 .sh 的 LF 编码，防 Windows CRLF。
- 生成 `.env.example`，README/STATUS 同步。

## Task 1: .gitattributes + env 模板
- 新增 `.gitattributes`：`*.sh text eol=lf`、`scripts/* text eol=lf`
- 新增 `.env.example`：分组注释（网络/数据/权限/密钥/端口），含 INTERNET_MODE 两档说明与可覆盖的 PIP_INDEX_URL/NPM_REGISTRY

## Task 2: fix-data-perms.sh
- 自动创建 `${DATA_DIR}/hermes` `${DATA_DIR}/postgres`，`mkdir -p`
- 按 `${DATA_UID}:${DATA_GID}` chown（有权限时）；无权限时打印清晰提示
- Makefile 提供 `make up` 自动先调用 fix-data-perms.sh

## Task 3: docker-compose.yml 重构
- 删除 override 文件
- 数据目录默认值改为 `${DATA_DIR:-./data}/hermes|postgres`
- control `user: "${DATA_UID:-1000}:${DATA_GID:-1000}"`
- 镜像源 build args 用 `${PIP_INDEX_URL}` / `${NPM_REGISTRY}`
- 隧道挂载改可选：用 `${TUNNEL_KEY_PATH:-./scripts/_no_tunnel_key}` 占位空文件，脚本检测 key 不存在即退出
- Hermes `HERMES_UID/GID` 与 DATA_UID/GID 对齐

## Task 4: 文档
- README 加“快速开始”：cp .env.example .env → 改 INTERNET_MODE → make up
- STATUS 更新环境变量表和启动命令

## 验证
- `git check-attr eol -- scripts/fix-data-perms.sh` → lf
- `bash -n scripts/fix-data-perms.sh`
- `docker compose config` 在默认/覆盖两种 env 下均能解析
