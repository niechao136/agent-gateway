from pathlib import Path
p = Path(r"D:\agent\agent-gateway\control\app\hermes\rag_sync.py")
s = p.read_text(encoding="utf-8")
old = '''    section = cfg.get("mcp")
    if not isinstance(section, dict):
        section = {}
    servers = section.get("servers")
    servers = list(servers) if isinstance(servers, list) else []
    servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == MCP_NAME)]
    if enabled:
        servers.append({
            "name": MCP_NAME,
            "transport": "stdio",
            "command": "python3",
            "args": [SERVER_SCRIPT],
            "description": "RAGFlow 知识库检索（dataset_ids 数组）",
        })
    if servers:
        section["servers"] = servers
        cfg["mcp"] = section
    else:
        section.pop("servers", None)
        if not section:
            cfg.pop("mcp", None)
    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return {"path": str(path), "mcp": MCP_NAME if enabled else None}'''
new = '''    # Hermes 真实格式：顶层 mcp_servers 字典（enabled + env），不是 mcp.servers 列表
    mcp_servers = cfg.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    mcp_servers.pop(MCP_NAME, None)
    if enabled:
        # 从 profile .env 读取 base64 配置，显式放进 MCP 子进程的 env
        env_path = profile_env_path(profile)
        env = {}
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("RAGFLOW_"):
                    k, _, v = line.partition("=")
                    env[k] = v
        mcp_servers[MCP_NAME] = {
            "command": "python3",
            "args": [SERVER_SCRIPT],
            "transport": "stdio",
            "enabled": True,
            "env": env,
            "description": "RAGFlow 知识库检索（dataset_ids 数组）",
        }
    if mcp_servers:
        cfg["mcp_servers"] = mcp_servers
    else:
        cfg.pop("mcp_servers", None)
    # 清理旧格式
    if isinstance(cfg.get("mcp"), dict):
        cfg["mcp"].pop("servers", None)
        if not cfg["mcp"]:
            cfg.pop("mcp", None)
    _atomic_write(path, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    return {"path": str(path), "mcp": MCP_NAME if enabled else None}'''
assert old in s, "sync block not found"
s = s.replace(old, new, 1)
# 需要 profile_env_path 导入：检查是否已从 provisioner 导入
if "profile_env_path" not in s:
    # 在 import 区附近添加
    s = s.replace("from .a2a import _atomic_write, profile_config_path",
                  "from .a2a import _atomic_write, profile_config_path, profile_env_path", 1)
p.write_text(s, encoding="utf-8")
print("RAG_SYNC_FORMAT_FIXED")
