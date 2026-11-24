# 架构补充事实（事实来源）

- 容器网络：自定义 bridge；hermes 单容器 s6 监管 gateway(8642)+dashboard(9119)，共享 `/opt/data`（两容器会争抢 gateway.lock）。
- control 与 hermes 同 uid:gid 1002:1003，解决 hermes-data 目录写权限问题。
- nginx 反代：`/api`→control，`/a2a`→control，`/`→web。
- sessions 的 profile 归属：`profile_of_conversation()` 唯一真相；软删保留 30 天。
- 工具集：`DEFAULT_DISABLED` 含 web/terminal/file/browser 等；`a2a` 已移除默认禁用。
- toolset forcing 规则：绑 A2A→强制 `a2a`；绑 Skill→强制 `skills`；绑带脚本 Skill→强制 `terminal`；解绑只解除强制、不主动关闭。
