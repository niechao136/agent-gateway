from pathlib import Path
p = Path(r"D:\agent\agent-gateway\control\app\hermes\rag_sync.py")
s = p.read_text(encoding="utf-8")
old = '''    # 清理旧格式
    if isinstance(cfg.get("mcp"), dict):
        cfg["mcp"].pop("servers", None)
        if not cfg["mcp"]:
            cfg.pop("mcp", None)
'''
assert old in s
s = s.replace(old, "", 1)
p.write_text(s, encoding="utf-8")
print("RAG_COMPAT_FIXED")
