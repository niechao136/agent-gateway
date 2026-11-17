# 生产部署记录（srv-01 新加坡）

## 访问地址

- 站点：http://43.156.187.79:10100
- 管理员登录：`/login` → 切到「管理员」标签

## 凭据

从 `/github/agent-gateway/.env` 读取：

```sh
grep -E "^ADMIN_(USERNAME|PASSWORD)=" .env
grep -E "^DASHBOARD_(USER|PASSWORD)=" .env
```

## 目录结构

```
/github/agent-gateway/
├── .env                     # 生产配置（含密钥，勿提交）
├── docker-compose.yml
├── docker-compose.override.yml  # 服务器覆盖：移除隧道、设内存上限
├── data/hermes/             # hermes 数据（profiles / state.db / config.yaml）
├── data/postgres/           # 控制层数据库
└── .build/                  # 构建日志
```

## 与本地开发的差异

| 项 | 本地 | 服务器 |
|---|---|---|
| 模型访问 | SSH 隧道 → srv-01:8899 | **直连 `172.17.0.1:8899`** |
| 隧道脚本 | 使用（cont-init） | **移除**（override 覆盖 volumes） |
| 端口 | 10099 | **10100** |
| hermes 数据 | ext4 挂载 | ext4（`/github` 在系统盘） |

服务器能直连 Google，本机 `gemini-proxy` 容器（8899）已反代，
所以 hermes 的 `base_url` 直接指向 `http://172.17.0.1:8899/v1beta/openai`。

## 常用操作

```sh
cd /github/agent-gateway

# 状态
sudo -u devops docker compose --env-file .env --profile full ps

# 更新代码
sudo -u devops git pull
sudo -u devops docker compose --env-file .env --profile full build
sudo -u devops docker compose --env-file .env --profile full up -d --no-build

# 重启单个服务
sudo -u devops docker compose --env-file .env restart hermes

# 看日志
sudo docker logs -f ag-hermes
```

## 资源限制

服务器总内存 3.6G，已用约 2.3G。`docker-compose.override.yml` 设了上限：

| 服务 | 上限 |
|---|---|
| hermes | 1200m |
| control | 384m |
| web | 256m |
| postgres | 256m |
| nginx | 64m |

## 注意事项

1. **构建时内存紧张**：`docker build` 曾多次被 OOM 杀掉。
   建议先 `sudo docker builder prune -af` 释放缓存再构建。
2. **镜像源**：服务器在新加坡，用默认 PyPI/npm 源比国内镜像快。
3. **hermes 镜像 3.23GB**：首次部署需拉取，磁盘要留足空间。
4. **数据备份**：`data/hermes` 和 `data/postgres` 是全部状态，
   定期 tar 备份即可。
