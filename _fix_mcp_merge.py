from pathlib import Path
p = Path(r"D:\agent\agent-gateway\control\app\hermes\mcp_sync.py")
s = p.read_text(encoding="utf-8")
old = '''    new_section = {}
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
new = '''    # 合并进已有 mcp_servers，保留其他来源（如 RAGFlow 内置 MCP）的条目
    new_section = dict(cfg.get("mcp_servers") or {})
    for e in entries:
        item = dict(e)
        name = item.pop("name")
        item["enabled"] = True
        new_section[name] = item
    if new_section:
        cfg["mcp_servers"] = new_section
    else:
        cfg.pop("mcp_servers", None)
'''
assert old in s
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("MCP_MERGE_FIXED")
