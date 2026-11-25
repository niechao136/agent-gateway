# agent-gateway 统一入口。所有环境用同一条命令启动；差异只来自 .env。
# 环境与镜像源/隧道的派生逻辑统一在 scripts/compose.sh（唯一入口）。
COMPOSE = sh scripts/compose.sh

.PHONY: help perms up build bootstrap down restart logs config test

help:
	@echo "make bootstrap  # 首次：建目录/修权限 + build + up"
	@echo "make up         # 建目录/修权限 + 启动（不重建）"
	@echo "make build      # 建目录/修权限 + 重建镜像"
	@echo "make config     # 查看最终渲染的 compose 配置"
	@echo "make logs / test / down / restart"

# 自动创建数据目录并统一属主（目录不存在时自动创建）
perms:
	@sh scripts/fix-data-perms.sh

up: perms
	$(COMPOSE) up -d --no-build

build: perms
	$(COMPOSE) build

bootstrap: perms
	$(COMPOSE) build
	$(COMPOSE) up -d --no-build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

config:
	$(COMPOSE) config

test:
	docker run --rm -v $(CURDIR)/control:/app -w /app agent-gateway-control:latest \
	  python -m pytest tests/ -q -p no:cacheprovider
