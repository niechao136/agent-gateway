from pathlib import Path
p = Path(r"D:\agent\agent-gateway\control\app\hermes\skill_sync.py")
s = p.read_text(encoding="utf-8")
old = '''def _skill_md(skill, *, strip_scripts: bool) -> str:
    desc = (skill.description or "").replace('"', "'")
    base = f"---\\nname: {skill.name}\\ndescription: \\"{desc}\\"\\n---\\n\\n{skill.content}\\n"
    return _inject_requires_terminal(base) if strip_scripts else base'''
new = '''def _skill_md(skill, *, strip_scripts: bool) -> str:
    desc = (skill.description or "").replace('"', "'")
    # 不再注入重复的 hermermes frontmatter：toolset_forcing 会在绑定带脚本
    # 的 skill 时强制开启 terminal 并禁止关闭，脚本始终可用；注入
    # requires_toolsets 会让 Hermes 隐藏技能且产生两个 --- frontmatter 块。
    return f"---\\nname: {skill.name}\\ndescription: \\"{desc}\\"\\n---\\n\\n{skill.content}\\n"'''
assert old in s
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("SKILL_SYNC_FIXED")
