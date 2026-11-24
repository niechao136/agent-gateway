from pathlib import Path
p = Path(r"D:\agent\agent-gateway\control\app\hermes\mcp_sync.py")
s = p.read_text(encoding="utf-8")
old = '''    entries = [build_mcp_entry(s) for s in servers]
    if entries:
        section = cfg.get("mcp")
        if not isinstance(section, dict):
            section = {}
        section["servers"] = entries
        cfg["mcp"] = section
    else:
        if isinstance(cfg.get("mcp"), dict):
            cfg["mcp"].pop("servers", None)
            if not cfg["mcp"]:
                cfg.pop("mcp", None)
'''
new = '''    entries = [build_mcp_entry(s) for s in servers]
    # Hermes 真实格式：顶层 mcp_servers 字典，name 作 key，带 enabled:true。
    # 旧格式 mcp.servers 列表不被 Hermes 加载（mcp list 显示 No MCP servers）。
    new_section = {}
    for e in entries:
        item = dict(e)
        name = item.pop("name")
        item["enabled"] = True
        new_section[name] = item
    # 清理旧格式，避免两份配置漂移
    if isinstance(cfg.get("mcp"), dict):
        cfg["mcp"].pop("servers", None)
        if not cfg["mcp"]:
            cfg.pop("mcp", None)
    if new_section:
        cfg["mcp_servers"] = new_section
    else:
        cfg.pop("mcp_servers", None)
'''
assert old in s, "apply block not found"
s = s.replace(old, new, 1)
old_read = '''    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        return []
    servers = mcp.get("servers")
    return servers if isinstance(servers, list) else []'''
new_read = '''    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # 优先读 Hermes 真实格式 mcp_servers（dict）
    real = cfg.get("mcp_servers")
    if isinstance(real, dict):
        out = []
        for name, item in real.items():
            if isinstance(item, dict):
                out.append({"name": name, **item})
        return out
    # 兼容旧格式
    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        return []
    servers = mcp.get("servers")
    return servers if isinstance(servers, list) else []'''
assert old_read in s, "read block not found"
s = s.replace(old_read, new_read, 1)
p.write_text(s, encoding="utf-8")
print("MCP_SYNC_FORMAT_FIXED")
