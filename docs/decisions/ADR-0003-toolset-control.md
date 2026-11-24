# ADR-0003：工具集真实开关是 `platform_toolsets`

- 状态：Accepted（A2A 自动调用排查后，2026-11-23）

## 背景
A2A 绑定后个人 Agent 不会自动调用 a2a；我们最初以为 `disabled_toolsets` 控制启停，改了无效。

## 决策
- Hermes 工具的真实启停由 profile `config.yaml` 的 `platform_toolsets.api_server` 控制；一旦显式配置就是 opt-in，必须包含 `hermes-api_server` 再加需要的工具集。
- 本项目 `disabled_toolsets` 只作为前端开关镜像；绑定资源强制开启的工具集，写入时**两处都处理**（从 disabled 移除 + 写入 platform_toolsets.api_server）。
- 启用命令用 `hermes -p <profile> tools enable <name>`；`HERMES_PROFILE` 环境变量无效。

## 后果
- 修复了 A2A 不自动调用（根因第 4 层）。
- 新增 `toolset_forcing.py` 统一计算强制集，绑定/解绑自动同步。
